"""
onq_autopilot/scraper.py
─────────────────────────
Playwright-based scraper for OnQ Brightspace.

Responsibilities
────────────────
1. scrape_assignments_list(org_unit_id)
   Navigate to the Assessments/Assignments tab and return every upcoming
   dropbox folder with its name, due date, folder ID, and description.

2. scrape_course_content(org_unit_id)
   Navigate to the Course Content tab and return the full topic tree —
   every module and topic with its title, type, and download URL.

3. find_content_for_assignment(assignment_name, topics)
   Heuristic matcher: given an assignment name, find the content topic
   that most likely contains the assignment brief (PDF or DOCX).

4. download_topic_file(org_unit_id, topic_id, save_path)
   Download a content topic file using the Valence API.

URL patterns (confirmed from D2L docs):
  Assignments list : /d2l/lms/dropbox/user/folders_list.d2l?ou={ou}
  Assignment detail: /d2l/lms/dropbox/user/folder_submit_files.d2l?db={db}&ou={ou}
  Content home     : /d2l/le/content/{ou}/Home
  API - content TOC: /d2l/api/le/{v}/{ou}/content/toc
  API - topic file : /d2l/api/le/{v}/{ou}/content/topics/{topicId}/file
"""

import os
import re
from pathlib import Path
from difflib import SequenceMatcher

from playwright.sync_api import sync_playwright, Page, BrowserContext
from .session import _BROWSER_DATA_DIR, BASE_URL, get_requests_session

OUTPUT_DIR  = Path(os.getenv("OUTPUT_DIR", "outputs"))
API_VERSION = "1.82"


# ──────────────────────────────────────────────────────────────────────────────
# Internal helpers
# ──────────────────────────────────────────────────────────────────────────────

def _make_context(pw, headless: bool = True) -> BrowserContext:
    _BROWSER_DATA_DIR.mkdir(exist_ok=True)
    return pw.chromium.launch_persistent_context(
        user_data_dir=str(_BROWSER_DATA_DIR),
        headless=headless,
        slow_mo=50,          # slight delay helps with dynamic D2L pages
    )


def _check_session(page: Page, context: BrowserContext):
    """Raise if we got redirected to a login page."""
    url = page.url
    if "login" in url or "microsoftonline" in url or "d2l/auth" in url:
        context.close()
        raise RuntimeError(
            "OnQ session expired. Run `python debug.py` to re-login, "
            "then try again."
        )


def _similarity(a: str, b: str) -> float:
    """0–1 string similarity score (case-insensitive)."""
    return SequenceMatcher(
        None,
        a.lower().strip(),
        b.lower().strip(),
    ).ratio()


# ──────────────────────────────────────────────────────────────────────────────
# 1. Assignments list (Assessments tab)
# ──────────────────────────────────────────────────────────────────────────────

def scrape_assignments_list(org_unit_id: int) -> list[dict]:
    """
    Navigate to the Assessments/Assignments tab for a course and return
    all visible dropbox folders.

    Returns a list of dicts:
      {
        "folder_id":    int,
        "name":         str,
        "due_date":     str,   # raw text as shown on page
        "instructions": str,   # text inside the assignment detail page
        "description":  str,   # short description from list view
        "status":       str,   # e.g. "No Submissions", "Submitted"
      }
    """
    url = f"{BASE_URL}/d2l/lms/dropbox/user/folders_list.d2l?ou={org_unit_id}"
    assignments = []

    with sync_playwright() as pw:
        context = _make_context(pw)
        page    = context.new_page()

        try:
            page.goto(url, wait_until="networkidle", timeout=30_000)
            _check_session(page, context)

            # Wait for the assignment table to appear
            try:
                page.wait_for_selector(
                    "table.d2l-table, .d2l-grid, [class*='dropbox']",
                    timeout=10_000,
                )
            except Exception:
                pass  # Page may use a different layout

            # Grab every link that goes to an individual assignment
            links = page.locator("a[href*='folder_submit_files.d2l']").all()

            for link in links:
                href  = link.get_attribute("href") or ""
                name  = link.inner_text().strip()

                # Extract folder ID from the URL (?db=XXXX)
                m = re.search(r"[?&]db=(\d+)", href)
                if not m:
                    continue
                folder_id = int(m.group(1))

                # Find the closest table row to get due date + status
                row = link.locator("xpath=ancestor::tr").first
                due_date = ""
                status   = ""
                desc     = ""
                try:
                    cells = row.locator("td").all()
                    # D2L column order: Name | Due Date | Submissions | Status
                    if len(cells) >= 2:
                        due_date = cells[1].inner_text(timeout=2000).strip()
                    if len(cells) >= 4:
                        status = cells[3].inner_text(timeout=2000).strip()
                except Exception:
                    pass

                # Fetch detailed instructions from the assignment page
                instructions = _scrape_assignment_detail(
                    page, org_unit_id, folder_id
                )

                assignments.append({
                    "folder_id":    folder_id,
                    "name":         name,
                    "due_date":     due_date,
                    "instructions": instructions,
                    "description":  desc,
                    "status":       status,
                })

        finally:
            context.close()

    return assignments


def _scrape_assignment_detail(
    page: Page, org_unit_id: int, folder_id: int
) -> str:
    """
    Open the assignment detail page in the same browser context and
    extract the full instructions text.
    """
    detail_url = (
        f"{BASE_URL}/d2l/lms/dropbox/user/folder_submit_files.d2l"
        f"?db={folder_id}&grpid=0&isprv=0&bp=0&ou={org_unit_id}"
    )
    try:
        page.goto(detail_url, wait_until="networkidle", timeout=20_000)

        # Try multiple known selectors for D2L assignment instructions
        selectors = [
            ".d2l-htmleditor-readonly",
            "[data-test-id='dropbox-folder-description']",
            ".dco-assignment-description",
            ".d2l-editor",
            ".d2l-le-scrollable",
            "d2l-html-block",             # web component used in newer D2L
        ]
        for sel in selectors:
            try:
                el = page.locator(sel).first
                text = el.inner_text(timeout=3000).strip()
                if text:
                    return text
            except Exception:
                continue
    except Exception:
        pass
    return ""


# ──────────────────────────────────────────────────────────────────────────────
# 2. Course content tree (Contents tab)
# ──────────────────────────────────────────────────────────────────────────────

def scrape_course_content_via_api(org_unit_id: int) -> list[dict]:
    """
    Use the D2L Valence REST API to get the full content TOC (Table of
    Contents) for a course. This is faster and more reliable than scraping
    the HTML content tree.

    Returns a flat list of topic dicts:
      {
        "topic_id":   int,
        "title":      str,
        "type":       str,    # "File", "Link", "Video", etc.
        "url":        str,    # API download URL for file topics
        "module":     str,    # parent module name
      }
    """
    s = get_requests_session()
    toc_url = f"{BASE_URL}/d2l/api/le/{API_VERSION}/{org_unit_id}/content/toc"

    try:
        resp = s.get(toc_url, timeout=15)
        resp.raise_for_status()
        toc = resp.json()
    except Exception as e:
        print(f"  [CONTENT] API content TOC failed ({e}) — falling back to scraper")
        return scrape_course_content_via_browser(org_unit_id)

    topics = []
    _flatten_toc(toc.get("Modules", []), topics, parent_module="")
    return topics


def _flatten_toc(modules: list, out: list, parent_module: str):
    """Recursively flatten the nested module/topic tree into a list."""
    for module in modules:
        mod_name = module.get("Title", "")
        full_mod = f"{parent_module} > {mod_name}".strip(" >")

        # Topics in this module
        for topic in module.get("Topics", []):
            topic_type = topic.get("TypeIdentifier", "")
            out.append({
                "topic_id": topic.get("TopicId"),
                "title":    topic.get("Title", ""),
                "type":     topic_type,
                "url":      topic.get("Url", ""),
                "module":   full_mod,
            })

        # Recurse into sub-modules
        _flatten_toc(module.get("Modules", []), out, full_mod)


def scrape_course_content_via_browser(org_unit_id: int) -> list[dict]:
    """
    Fallback: navigate the Content page with Playwright and extract
    topic titles + links from the rendered HTML tree.
    """
    url = f"{BASE_URL}/d2l/le/content/{org_unit_id}/Home"
    topics = []

    with sync_playwright() as pw:
        context = _make_context(pw)
        page    = context.new_page()

        try:
            page.goto(url, wait_until="networkidle", timeout=30_000)
            _check_session(page, context)

            # Wait for content tree
            try:
                page.wait_for_selector(
                    ".d2l-le-TreeItem, .d2l-datalist-item, [class*='content']",
                    timeout=10_000,
                )
            except Exception:
                pass

            # Grab all links in the content panel
            links = page.locator(
                "a[href*='/content/'], a[href*='/topics/'], a[href*='.pdf'], a[href*='.docx']"
            ).all()

            for link in links:
                href  = link.get_attribute("href") or ""
                title = link.inner_text().strip()
                if not title:
                    continue

                # Try to extract topic ID
                m = re.search(r"/topics?/(\d+)", href)
                topic_id = int(m.group(1)) if m else None

                # Classify type by extension or URL hint
                ext = Path(href.split("?")[0]).suffix.lower()
                if ext == ".pdf":
                    ftype = "File/PDF"
                elif ext in (".docx", ".doc"):
                    ftype = "File/DOCX"
                elif ext in (".pptx", ".ppt"):
                    ftype = "File/Presentation"
                else:
                    ftype = "Link"

                topics.append({
                    "topic_id": topic_id,
                    "title":    title,
                    "type":     ftype,
                    "url":      href if href.startswith("http") else BASE_URL + href,
                    "module":   "",
                })

        finally:
            context.close()

    return topics


# ──────────────────────────────────────────────────────────────────────────────
# 3. Match assignment → content topic
# ──────────────────────────────────────────────────────────────────────────────

def find_content_for_assignment(
    assignment_name: str,
    topics: list[dict],
    threshold: float = 0.45,
) -> list[dict]:
    """
    Given an assignment name, score every content topic by name similarity
    and return those above the threshold, ranked best-first.

    Also flags topics whose titles contain assignment keywords like
    "brief", "specification", "instructions", "rubric", "handout".

    Returns: list of topic dicts with an added "score" key.
    """
    BRIEF_KEYWORDS = {"brief", "spec", "specification", "instructions",
                      "rubric", "handout", "description", "outline",
                      "assignment", "lab", "project", "report"}

    scored = []
    for topic in topics:
        # Only consider file-type topics (PDFs, DOCX)
        ftype = topic.get("type", "").lower()
        if "file" not in ftype and "pdf" not in ftype and "docx" not in ftype:
            continue

        title = topic.get("title", "")
        sim   = _similarity(assignment_name, title)

        # Boost topics whose title contains brief/spec/rubric keywords
        title_lower = title.lower()
        if any(kw in title_lower for kw in BRIEF_KEYWORDS):
            sim = min(sim + 0.2, 1.0)

        # Boost if any word from the assignment name appears in the title
        assign_words = set(re.findall(r"\w+", assignment_name.lower()))
        topic_words  = set(re.findall(r"\w+", title_lower))
        word_overlap  = len(assign_words & topic_words) / max(len(assign_words), 1)
        sim = min(sim + word_overlap * 0.15, 1.0)

        if sim >= threshold:
            scored.append({**topic, "score": round(sim, 3)})

    return sorted(scored, key=lambda x: x["score"], reverse=True)


# ──────────────────────────────────────────────────────────────────────────────
# 4. Download a content topic file
# ──────────────────────────────────────────────────────────────────────────────

def download_topic_file(
    org_unit_id: int,
    topic_id: int,
    save_path: str,
) -> str | None:
    """
    Download a content topic's file using the Valence API.
    Returns the local save path, or None on failure.

    API: GET /d2l/api/le/{v}/{ou}/content/topics/{topicId}/file
    """
    s   = get_requests_session()
    url = (
        f"{BASE_URL}/d2l/api/le/{API_VERSION}"
        f"/{org_unit_id}/content/topics/{topic_id}/file"
    )
    try:
        resp = s.get(url, stream=True, timeout=60, allow_redirects=True)
        resp.raise_for_status()

        Path(save_path).parent.mkdir(parents=True, exist_ok=True)
        with open(save_path, "wb") as f:
            for chunk in resp.iter_content(8192):
                f.write(chunk)
        return save_path
    except Exception as e:
        print(f"  [CONTENT] Could not download topic {topic_id}: {e}")
        return None
