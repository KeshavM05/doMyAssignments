"""
onq_autopilot/pipeline.py
──────────────────────────
Core orchestration loop.

Run modes:
  python -m onq_autopilot.pipeline --once    # scan all courses once
  python -m onq_autopilot.pipeline --watch   # poll every POLL_INTERVAL_SECONDS

Workflow per assignment:
  1. Scrape Assessments tab  →  list of upcoming assignments
  2. Scrape Contents tab     →  full topic tree (via API, falls back to browser)
  3. Match assignment name   →  find the most relevant content PDF/DOCX
  4. Download matched files  →  save to outputs/<ou>/<folder>/attachments/
  5. Extract text            →  from PDFs, DOCX, and assignment instructions
  6. Build AssignmentBundle  →  structured dict passed to LLM
  7. LLM call                →  returns LaTeX body
  8. latex_output.py         →  wraps in document, saves .tex, compiles .pdf
  9. Mark seen               →  state/seen.json records processed IDs

No submission. No AUTO_SUBMIT. Output stays on your laptop.

State tracking: state/seen.json  —  delete an entry to re-process.
"""

import json
import os
import time
import argparse
from pathlib import Path
from datetime import datetime, timezone

from dotenv import load_dotenv
load_dotenv()

from . import d2l_client as d2l
from .scraper import (
    scrape_assignments_list,
    scrape_course_content_via_api,
    find_content_for_assignment,
    download_topic_file,
)
from .extractor import build_assignment_bundle, extract_text_from_file
from .llm import complete
from .latex_output import generate_output

OUTPUT_DIR    = Path(os.getenv("OUTPUT_DIR", "outputs"))
STATE_DIR     = Path("state")
SEEN_FILE     = STATE_DIR / "seen.json"
SKIP_KEYWORDS = {t.strip().lower() for t in os.getenv("SKIP_TYPES", "quiz,exam,midterm,final").split(",")}
POLL_INTERVAL = int(os.getenv("POLL_INTERVAL_SECONDS", "300"))
MAX_CONTENT_DOCS = int(os.getenv("MAX_CONTENT_DOCS", "2"))  # cap content docs sent to LLM


# ──────────────────────────────────────────────────────────────────────────────
# State management
# ──────────────────────────────────────────────────────────────────────────────

def load_seen() -> set[str]:
    if SEEN_FILE.exists():
        return set(json.loads(SEEN_FILE.read_text()))
    return set()


def mark_seen(key: str):
    STATE_DIR.mkdir(exist_ok=True)
    seen = load_seen()
    seen.add(key)
    SEEN_FILE.write_text(json.dumps(sorted(seen), indent=2))


# ──────────────────────────────────────────────────────────────────────────────
# Per-assignment processing
# ──────────────────────────────────────────────────────────────────────────────

def process_assignment(course: dict, assignment: dict) -> dict:
    """
    Full pipeline for a single assignment.

    Args:
        course:     OrgUnit enrollment dict from d2l_client
        assignment: Assignment dict from scrape_assignments_list()

    Returns result dict with tex_path, pdf_path, bundle keys.
    """
    org_unit_id = course["OrgUnit"]["Id"]
    folder_id   = assignment["folder_id"]
    key         = f"{org_unit_id}:{folder_id}"

    print(f"\n{'='*62}")
    print(f"  Course     : {course['OrgUnit']['Name']}")
    print(f"  Assignment : {assignment['name']}")
    print(f"  Due        : {assignment.get('due_date', 'N/A')}")
    print(f"{'='*62}")

    # ── Step 1: Get API folder metadata (for attachments + score) ────────────
    folder_meta = {}
    try:
        folder_meta = d2l.get_dropbox_folder(org_unit_id, folder_id)
    except Exception as e:
        print(f"  [!] Could not fetch folder metadata via API ({e}) — using scraped data")

    # ── Step 2: Download instructor-attached files from the dropbox ──────────
    attachment_paths = []
    for att in folder_meta.get("Attachments", []):
        file_id   = att["FileId"]
        file_name = att["FileName"]
        save_path = (
            OUTPUT_DIR / str(org_unit_id) / str(folder_id)
            / "attachments" / file_name
        )
        print(f"  [↓] Downloading dropbox attachment: {file_name}")
        try:
            d2l.download_folder_attachment(
                org_unit_id, folder_id, file_id, str(save_path)
            )
            attachment_paths.append(str(save_path))
        except Exception as e:
            print(f"      Failed: {e}")

    # ── Step 3: Search course content for matching documents ─────────────────
    print("  [🔍] Scanning course content for related documents...")
    content_doc_paths = []
    try:
        topics = scrape_course_content_via_api(org_unit_id)
        print(f"      Found {len(topics)} content topics.")

        matches = find_content_for_assignment(assignment["name"], topics)
        if matches:
            print(f"      {len(matches)} matching topic(s) found:")
            for m in matches[:MAX_CONTENT_DOCS]:
                print(f"        [{m['score']:.2f}] {m['title']} ({m['type']})")
        else:
            print("      No strongly matching content topics found.")

        # Download top matches
        for topic in matches[:MAX_CONTENT_DOCS]:
            if topic.get("topic_id") is None:
                continue
            ext      = Path(str(topic.get("url", ""))).suffix or ".pdf"
            filename = f"content_{topic['topic_id']}{ext}"
            save_path = (
                OUTPUT_DIR / str(org_unit_id) / str(folder_id)
                / "content" / filename
            )
            result = download_topic_file(
                org_unit_id, topic["topic_id"], str(save_path)
            )
            if result:
                content_doc_paths.append({
                    "name": topic["title"],
                    "path": result,
                })
    except Exception as e:
        print(f"  [!] Content scan failed ({e})")

    # ── Step 4: Build AssignmentBundle ───────────────────────────────────────
    # Merge scraped instructions with API metadata
    if assignment.get("instructions") and folder_meta:
        folder_meta["CustomInstructions"] = {
            "Html": "",
            "Text": assignment["instructions"],
        }

    bundle = build_assignment_bundle(course, folder_meta or {
        "Id":               folder_id,
        "Name":             assignment["name"],
        "DueDate":          assignment.get("due_date"),
        "CustomInstructions": {"Html": "", "Text": assignment.get("instructions", "")},
        "Assessment":       None,
        "SubmissionType":   "0",
        "TotalUsersWithSubmissions": 0,
        "Attachments":      [],
    }, attachment_paths)

    # Attach content doc texts to the bundle
    bundle["org_unit_id"] = org_unit_id
    bundle["folder_id"]   = folder_id
    bundle["content_docs"] = []
    for doc in content_doc_paths:
        text = extract_text_from_file(doc["path"])
        bundle["content_docs"].append({"name": doc["name"], "text": text})

    # ── Step 5: LLM call ─────────────────────────────────────────────────────
    provider = os.getenv("LLM_PROVIDER", "openai")
    print(f"  [🤖] Sending to {provider}...")
    latex_body = complete(bundle)

    # ── Step 6: LaTeX → PDF ──────────────────────────────────────────────────
    print("  [📄] Generating LaTeX and compiling PDF...")
    result = generate_output(latex_body, bundle)

    print(f"  [✓] Done.")
    if result["pdf_path"]:
        print(f"       PDF  → {result['pdf_path']}")
    print(f"       TeX  → {result['tex_path']}")

    mark_seen(key)
    return {**result, "bundle": bundle}


# ──────────────────────────────────────────────────────────────────────────────
# Scan loop
# ──────────────────────────────────────────────────────────────────────────────

def scan_once():
    seen = load_seen()
    print(f"\n[SCAN] {datetime.now().strftime('%H:%M:%S')} — Fetching active courses...")

    try:
        courses = d2l.get_active_courses()
    except Exception as e:
        print(f"[SCAN] Could not fetch courses via API ({e}).")
        print("       Make sure your session is valid — run python debug.py")
        return

    print(f"[SCAN] {len(courses)} active course(s).")

    for course in courses:
        org_unit_id   = course["OrgUnit"]["Id"]
        course_name   = course["OrgUnit"]["Name"]

        print(f"\n[COURSE] {course_name} (ou={org_unit_id})")

        # Get assignments from the Assessments tab via scraper
        try:
            assignments = scrape_assignments_list(org_unit_id)
            print(f"  Found {len(assignments)} assignment(s) on Assessments tab.")
        except Exception as e:
            print(f"  [!] Could not scrape assignments: {e}")
            continue

        for assignment in assignments:
            folder_id = assignment["folder_id"]
            key       = f"{org_unit_id}:{folder_id}"

            # Already processed
            if key in seen:
                continue

            # Skip by keyword
            name_lower = assignment["name"].lower()
            if any(kw in name_lower for kw in SKIP_KEYWORDS):
                print(f"  [SKIP] {assignment['name']} (matched skip list)")
                mark_seen(key)
                continue

            # Skip past-due assignments
            raw_due = assignment.get("due_date", "")
            # (due_date from scraper is a display string, not ISO — skip date check
            #  unless it's parseable)

            try:
                process_assignment(course, assignment)
            except Exception as e:
                import traceback
                print(f"  [ERROR] {assignment['name']}: {e}")
                traceback.print_exc()


def watch():
    print(f"[WATCH] Polling every {POLL_INTERVAL}s. Ctrl+C to stop.")
    while True:
        try:
            scan_once()
        except Exception as e:
            print(f"[ERROR] Scan failed: {e}")
        print(f"\n[WATCH] Sleeping {POLL_INTERVAL}s...")
        time.sleep(POLL_INTERVAL)


# ──────────────────────────────────────────────────────────────────────────────
# CLI
# ──────────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="ONQ Autopilot")
    group  = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--once",  action="store_true", help="Scan once and exit")
    group.add_argument("--watch", action="store_true", help="Poll continuously")
    args = parser.parse_args()

    if args.once:
        scan_once()
    else:
        watch()
