"""
onq_autopilot/pipeline.py
──────────────────────────
Core orchestration loop.

Run modes:
  python -m onq_autopilot.pipeline --once    # process all pending assignments now
  python -m onq_autopilot.pipeline --watch   # poll every POLL_INTERVAL_SECONDS

State tracking: a simple JSON file (state/seen.json) records which
folder IDs have already been processed so we don't re-do them.
"""

import json
import os
import time
import argparse
from pathlib import Path
from datetime import datetime

from dotenv import load_dotenv
load_dotenv()

from . import d2l_client as d2l
from .extractor import build_assignment_bundle
from .llm import complete

OUTPUT_DIR     = Path(os.getenv("OUTPUT_DIR", "outputs"))
STATE_DIR      = Path("state")
SEEN_FILE      = STATE_DIR / "seen.json"
SKIP_TYPES     = {t.strip().lower() for t in os.getenv("SKIP_TYPES", "quiz,exam").split(",")}
POLL_INTERVAL  = int(os.getenv("POLL_INTERVAL_SECONDS", "300"))
AUTO_SUBMIT    = os.getenv("AUTO_SUBMIT", "false").lower() == "true"


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

def process_assignment(course: dict, folder: dict):
    org_unit_id = course["OrgUnit"]["Id"]
    folder_id   = folder["Id"]
    key         = f"{org_unit_id}:{folder_id}"

    print(f"\n{'='*60}")
    print(f"  Course  : {course['OrgUnit']['Name']}")
    print(f"  Assignment: {folder['Name']}")
    print(f"  Due     : {folder.get('DueDate', 'N/A')}")
    print(f"  Type    : {folder.get('SubmissionType')}")
    print(f"{'='*60}")

    # Download instructor-attached files (the brief / rubric PDFs)
    attachment_paths = []
    for att in folder.get("Attachments", []):
        file_id   = att["FileId"]
        file_name = att["FileName"]
        save_path = OUTPUT_DIR / str(org_unit_id) / str(folder_id) / "attachments" / file_name
        print(f"  [↓] Downloading attachment: {file_name}")
        d2l.download_folder_attachment(org_unit_id, folder_id, file_id, str(save_path))
        attachment_paths.append(str(save_path))

    # Build the structured bundle
    bundle = build_assignment_bundle(course, folder, attachment_paths)

    # Call the LLM
    print(f"  [🤖] Sending to LLM ({os.getenv('LLM_PROVIDER', 'openai')})...")
    answer = complete(bundle)

    # Save the answer locally
    out_dir = OUTPUT_DIR / str(org_unit_id) / str(folder_id)
    out_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_file  = out_dir / f"answer_{timestamp}.md"
    out_file.write_text(answer, encoding="utf-8")
    print(f"  [✓] Answer saved → {out_file}")

    # Optionally auto-submit
    if AUTO_SUBMIT:
        sub_type = str(folder.get("SubmissionType", "0"))
        if sub_type in ("1", "4"):  # Text or File-or-Text
            print("  [→] Auto-submitting...")
            d2l.submit_text_submission(
                org_unit_id, folder_id,
                text_html=f"<p>{answer.replace(chr(10), '<br>')}</p>",
                comment="Submitted via ONQ Autopilot",
            )
            print("  [✓] Submitted!")
        else:
            print("  [!] AUTO_SUBMIT=true but submission type is not Text — skipping auto-submit.")
    else:
        print("  [i] AUTO_SUBMIT=false — review output and submit manually.")

    mark_seen(key)


# ──────────────────────────────────────────────────────────────────────────────
# Main scan loop
# ──────────────────────────────────────────────────────────────────────────────

def scan_once():
    """Scan all active courses for new, unprocessed assignments."""
    seen = load_seen()
    print(f"\n[SCAN] {datetime.now().strftime('%H:%M:%S')} — Fetching active courses...")

    courses = d2l.get_active_courses()
    print(f"[SCAN] Found {len(courses)} active courses.")

    for course in courses:
        org_unit_id = course["OrgUnit"]["Id"]
        try:
            folders = d2l.get_dropbox_folders(org_unit_id)
        except Exception as e:
            print(f"  [!] Could not fetch folders for {course['OrgUnit']['Name']}: {e}")
            continue

        for folder in folders:
            folder_id = folder["Id"]
            key       = f"{org_unit_id}:{folder_id}"

            # Skip if already processed
            if key in seen:
                continue

            # Skip assignment types that are excluded
            folder_name_lower = folder["Name"].lower()
            if any(skip in folder_name_lower for skip in SKIP_TYPES):
                print(f"  [SKIP] {folder['Name']} (matched skip list)")
                mark_seen(key)
                continue

            # Skip if due date has already passed
            due = folder.get("DueDate")
            if due:
                from datetime import timezone
                due_dt = datetime.fromisoformat(due.replace("Z", "+00:00"))
                if due_dt < datetime.now(tz=timezone.utc):
                    print(f"  [SKIP] {folder['Name']} (past due)")
                    mark_seen(key)
                    continue

            try:
                process_assignment(course, folder)
            except Exception as e:
                print(f"  [ERROR] Failed to process {folder['Name']}: {e}")


def watch():
    """Continuously poll for new assignments."""
    print(f"[WATCH] Polling every {POLL_INTERVAL}s. Press Ctrl+C to stop.")
    while True:
        try:
            scan_once()
        except Exception as e:
            print(f"[ERROR] Scan failed: {e}")
        print(f"[WATCH] Sleeping {POLL_INTERVAL}s...")
        time.sleep(POLL_INTERVAL)


# ──────────────────────────────────────────────────────────────────────────────
# CLI entry-point
# ──────────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="ONQ Autopilot — LLM Assignment Pipeline")
    group  = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--once",  action="store_true", help="Run one scan then exit")
    group.add_argument("--watch", action="store_true", help="Poll continuously")
    args = parser.parse_args()

    if args.once:
        scan_once()
    else:
        watch()
