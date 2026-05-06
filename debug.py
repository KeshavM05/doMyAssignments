"""
debug.py — ONQ Autopilot connection tester
──────────────────────────────────────────
Run this FIRST before the full pipeline to verify each layer works.

Usage:
    python debug.py

Steps it tests:
  1. Session — can we log in and get valid cookies?
  2. whoami  — does the D2L API accept our cookies?
  3. Courses — can we list your enrolled courses?
  4. Folders — can we list assignments in the first course?
  5. Scraper — can Playwright load an assignment page?
"""

import sys
import json
import os
from pathlib import Path

# Make sure we can import the package from this directory
sys.path.insert(0, str(Path(__file__).parent))

from dotenv import load_dotenv
load_dotenv()

from onq_autopilot.session import get_requests_session
from onq_autopilot import d2l_client as d2l

BASE_URL    = os.getenv("ONQ_BASE_URL", "https://onq.queensu.ca")
API_VERSION = "1.82"


def separator(title: str):
    print(f"\n{'─'*60}")
    print(f"  {title}")
    print(f"{'─'*60}")


def step(label: str, ok: bool, detail: str = ""):
    icon = "✅" if ok else "❌"
    line = f"  {icon}  {label}"
    if detail:
        line += f"\n       {detail}"
    print(line)


# ──────────────────────────────────────────────────────────────────────────────

separator("STEP 1: Browser login / session cookies")
try:
    s = get_requests_session()
    step("get_requests_session()", True, "Session object created")
except Exception as e:
    step("get_requests_session()", False, str(e))
    print("\n[FATAL] Cannot continue without a session. Exiting.")
    sys.exit(1)

# ──────────────────────────────────────────────────────────────────────────────

separator("STEP 2: /whoami — verify D2L API accepts cookies")
try:
    resp = s.get(
        f"{BASE_URL}/d2l/api/lp/{API_VERSION}/users/whoami",
        timeout=10,
        allow_redirects=False,
    )
    if resp.status_code == 200:
        me = resp.json()
        step("/whoami", True,
             f"Identifier={me.get('Identifier')}  "
             f"UniqueName={me.get('UniqueName')}  "
             f"FirstName={me.get('FirstName')}")
    else:
        step("/whoami", False, f"HTTP {resp.status_code} — {resp.text[:200]}")
        print("\n[WARN] The API rejected our cookies.")
        print("  This might mean the D2L Valence REST API requires OAuth on OnQ.")
        print("  We'll still try the scraper path below.")
except Exception as e:
    step("/whoami", False, str(e))

# ──────────────────────────────────────────────────────────────────────────────

separator("STEP 3: Enrollments — list your active courses")
courses = []
try:
    enrollments = d2l.get_my_enrollments()
    courses     = d2l.get_active_courses()
    step(
        "get_active_courses()",
        True,
        f"{len(courses)} active / {len(enrollments)} total enrollments"
    )
    for e in courses[:8]:  # show up to 8
        ou = e.get("OrgUnit", {})
        print(f"       • [{ou.get('Id')}] {ou.get('Name')} ({ou.get('Code')})")
except Exception as e:
    step("get_active_courses()", False, str(e))

# ──────────────────────────────────────────────────────────────────────────────

separator("STEP 4: Dropbox folders — list assignments in first course")
if courses:
    first_course = courses[0]
    org_id = first_course["OrgUnit"]["Id"]
    name   = first_course["OrgUnit"]["Name"]
    try:
        folders = d2l.get_dropbox_folders(org_id)
        step(
            f"get_dropbox_folders({org_id})",
            True,
            f"{len(folders)} assignment(s) in '{name}'"
        )
        for f in folders[:5]:  # show up to 5
            print(f"       • [{f.get('Id')}] {f.get('Name')}  due={f.get('DueDate','N/A')}")
    except Exception as e:
        step(f"get_dropbox_folders({org_id})", False, str(e))
        print("  Hint: if you see 403, the REST API may require OAuth for this endpoint.")
        print("  In that case, the scraper-only mode will still work.")
else:
    print("  [SKIP] No courses found — skipping folder test.")

# ──────────────────────────────────────────────────────────────────────────────

separator("STEP 5: Scraper — load the OnQ courses page via Playwright")
try:
    from playwright.sync_api import sync_playwright
    from onq_autopilot.session import _BROWSER_DATA_DIR

    with sync_playwright() as pw:
        ctx = pw.chromium.launch_persistent_context(
            user_data_dir=str(_BROWSER_DATA_DIR),
            headless=True,
        )
        page = ctx.new_page()
        page.goto(f"{BASE_URL}/d2l/home", wait_until="networkidle", timeout=20_000)
        title = page.title()
        url   = page.url
        ctx.close()

    on_onq = "onq.queensu.ca" in url or "queensu" in url.lower()
    step(
        "Playwright headless load",
        on_onq,
        f"title='{title}'  url={url}"
    )
    if not on_onq:
        print("  Hint: if you landed on a login page, your browser session needs refresh.")
        print("  Delete .session_state.json and re-run debug.py")
except Exception as e:
    step("Playwright headless load", False, str(e))

# ──────────────────────────────────────────────────────────────────────────────

separator("SUMMARY")
print("""
Next steps:
  • If all green → run the full pipeline:
      python -m onq_autopilot.pipeline --once

  • If Step 2 (/whoami) fails but Step 5 (scraper) works:
      The D2L REST API is blocked for non-OAuth clients on OnQ.
      We'll need to switch to scraper-only mode for data retrieval.
      Open a GitHub issue or continue the conversation with your AI agent.

  • If Step 5 (scraper) fails:
      Delete .session_state.json and .browser_profile/ and retry.
      This forces a fresh login.
""")
