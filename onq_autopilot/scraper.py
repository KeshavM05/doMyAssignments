"""
onq_autopilot/scraper.py
─────────────────────────
Playwright-based HTML scraper for OnQ pages.

Used as a FALLBACK when the D2L REST API doesn't expose what we need —
for example, when an assignment's instructions are only rendered in HTML
and don't come back cleanly through the API, or when we need to scrape
the assignment submission form to fill it in via browser automation.

All scraper functions receive a Playwright `page` object and assume the
browser is already logged in (session restored via storageState).
"""

import os
import time
from pathlib import Path
from playwright.sync_api import sync_playwright, Page, BrowserContext

from .session import _BROWSER_DATA_DIR, BASE_URL, ensure_session, _save_state

OUTPUT_DIR = Path(os.getenv("OUTPUT_DIR", "outputs"))


# ──────────────────────────────────────────────────────────────────────────────
# Browser context factory
# ──────────────────────────────────────────────────────────────────────────────

def _make_context(pw, headless: bool = True) -> BrowserContext:
    """
    Returns a persistent Chromium context with the saved browser profile.
    headless=True for background runs, headless=False for debugging.
    """
    _BROWSER_DATA_DIR.mkdir(exist_ok=True)
    return pw.chromium.launch_persistent_context(
        user_data_dir=str(_BROWSER_DATA_DIR),
        headless=headless,
        args=["--start-maximized"],
        no_viewport=True,
    )


# ──────────────────────────────────────────────────────────────────────────────
# Assignment page scraper
# ──────────────────────────────────────────────────────────────────────────────

def scrape_assignment_page(org_unit_id: int, folder_id: int) -> dict:
    """
    Navigate to the OnQ assignment page and scrape:
      - Full instructions HTML (sometimes richer than the API returns)
      - Any linked external URLs in the instructions
      - Due date (as rendered in the UI)

    Returns a dict:
      {
        "instructions_html": str,
        "instructions_text": str,
        "external_links": [str, ...],
        "due_date_display": str,
      }
    """
    url = (
        f"{BASE_URL}/d2l/lms/dropbox/user/folder_submit_files.d2l"
        f"?db={folder_id}&grpid=0&isprv=0&bp=0&ou={org_unit_id}"
    )

    with sync_playwright() as pw:
        context = _make_context(pw, headless=True)
        page = context.new_page()

        try:
            page.goto(url, wait_until="networkidle", timeout=30_000)
            _handle_expired_session(page, context)

            # Extract instructions
            instructions_html = ""
            instructions_text = ""
            try:
                instr_el = page.locator(
                    ".d2l-htmleditor-readonly, "
                    ".d2l-editor, "
                    "[data-test-id='dropbox-folder-description'], "
                    ".dco-assignment-description"
                ).first
                instr_el.wait_for(timeout=5000)
                instructions_html = instr_el.inner_html()
                instructions_text = instr_el.inner_text()
            except Exception:
                pass

            # Extract due date from UI (more human-readable)
            due_date_display = ""
            try:
                due_el = page.locator(
                    "[data-test-id='dropbox-due-date'], "
                    ".d2l-datetime-display, "
                    ".dco-assignment-due-date"
                ).first
                due_date_display = due_el.inner_text(timeout=3000)
            except Exception:
                pass

            # Grab any external links in instructions
            external_links = []
            try:
                links = page.locator(
                    ".d2l-htmleditor-readonly a, "
                    ".dco-assignment-description a"
                ).all()
                for link in links:
                    href = link.get_attribute("href")
                    if href and href.startswith("http"):
                        external_links.append(href)
            except Exception:
                pass

        finally:
            context.close()

    return {
        "instructions_html": instructions_html,
        "instructions_text": instructions_text,
        "external_links":    external_links,
        "due_date_display":  due_date_display,
    }


def _handle_expired_session(page: Page, context: BrowserContext):
    """
    If D2L redirected us to the login page, it means the persistent
    profile session has expired. Re-trigger login and update the state.
    """
    current_url = page.url
    if "login" in current_url or "microsoftonline" in current_url:
        print("[SCRAPER] Session expired — re-logging in (browser will open)...")
        from .session import _browser_login
        # Need headful for MFA
        context.close()
        new_cookies = _browser_login()
        _save_state(new_cookies)
        raise RuntimeError(
            "Session expired and was refreshed. Please re-run the pipeline."
        )


# ──────────────────────────────────────────────────────────────────────────────
# Submission via browser (fallback for File-type assignments)
# ──────────────────────────────────────────────────────────────────────────────

def submit_via_browser(
    org_unit_id: int,
    folder_id: int,
    answer_text: str,
    comment: str = "",
) -> bool:
    """
    Uses Playwright to open the OnQ submission form and type in the answer.
    This is the fallback when the API submission doesn't work.

    Returns True if submission succeeded.
    """
    if os.getenv("AUTO_SUBMIT", "false").lower() != "true":
        raise PermissionError(
            "AUTO_SUBMIT is disabled. Set AUTO_SUBMIT=true to enable."
        )

    url = (
        f"{BASE_URL}/d2l/lms/dropbox/user/folder_submit_files.d2l"
        f"?db={folder_id}&grpid=0&isprv=0&bp=0&ou={org_unit_id}"
    )

    with sync_playwright() as pw:
        context = _make_context(pw, headless=False)  # visible for submission safety
        page = context.new_page()

        try:
            page.goto(url, wait_until="networkidle", timeout=30_000)
            _handle_expired_session(page, context)

            # Click the "Add a File" or text submission tab if present
            # D2L's text editor is an iframe-based rich text editor (TinyMCE/Brightspace Editor)
            try:
                text_tab = page.locator(
                    "text=Add Text, [data-test-id='text-submission-tab']"
                ).first
                text_tab.click(timeout=3000)
            except Exception:
                pass  # May already be on text input

            # Find the TinyMCE iframe and type in it
            frame = page.frame_locator("iframe.tox-edit-area__iframe, iframe[id*='tinymce']").first
            body  = frame.locator("body")
            body.click()
            body.fill(answer_text)

            # Add a comment if the comment field exists
            if comment:
                try:
                    comment_field = page.locator(
                        "[data-test-id='submission-comment'], "
                        "textarea[name*='comment'], "
                        "#d2l_comments"
                    ).first
                    comment_field.fill(comment, timeout=3000)
                except Exception:
                    pass

            # Submit
            submit_btn = page.locator(
                "button[type='submit'], "
                "[data-test-id='submit-button'], "
                "text=Submit"
            ).first
            submit_btn.click()

            # Wait for confirmation
            page.wait_for_url("**dropbox**", timeout=15_000)
            time.sleep(2)
            print("[SCRAPER] Submission completed via browser.")
            return True

        except Exception as e:
            print(f"[SCRAPER] Browser submission failed: {e}")
            return False

        finally:
            context.close()
