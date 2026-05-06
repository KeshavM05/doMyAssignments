# ONQ Autopilot — First Run Guide

## Current repo state (3 commits)

```
ab072b8  fix: remove stale auth.py, improve session caching, add debug.py
5c897d5  refactor: replace OAuth2 with Playwright cookie-based session
c063a73  feat: initial ONQ Autopilot scaffold
```

## Files on disk

```
d:\d2l\
├── debug.py                     ← Run this first to test every layer
├── .env.example                 ← Copy → .env, fill in your LLM key
├── pyproject.toml
├── README.md
└── onq_autopilot/
    ├── session.py               ← Browser login + cookie cache
    ├── d2l_client.py            ← D2L REST API wrappers
    ├── scraper.py               ← Playwright HTML scraper
    ├── extractor.py             ← PDF/DOCX/HTML text extraction
    ├── llm.py                   ← OpenAI / Anthropic / Google dispatch
    └── pipeline.py              ← Main orchestrator (--once / --watch)
```

---

## Step-by-step setup

### 1. Create & activate a virtual environment

```powershell
cd d:\d2l
python -m venv .venv
.venv\Scripts\activate
```

### 2. Install Python dependencies

```powershell
pip install -e .
```

### 3. Install the Playwright Chromium browser (~150 MB)

```powershell
playwright install chromium
```

### 4. Create your `.env` file

```powershell
copy .env.example .env
```

Open `.env` and fill in **at minimum**:

```env
LLM_PROVIDER=openai          # or anthropic / google
OPENAI_API_KEY=sk-...        # your actual key
```

Everything else has sensible defaults.

### 5. Run the debug script (tests every layer)

```powershell
python debug.py
```

**What happens:**
- A Chromium browser window opens
- Navigate to OnQ, log in with your NetID + password + MFA
- The browser closes automatically once you're on the home page
- The script then tests: cookies → /whoami API → course list → assignment list → headless scraper

**Expected output (all green):**
```
──────────────────────────────────────────────────────────
  STEP 1: Browser login / session cookies
──────────────────────────────────────────────────────────
  ✅  get_requests_session()
       Session object created

──────────────────────────────────────────────────────────
  STEP 2: /whoami — verify D2L API accepts cookies
──────────────────────────────────────────────────────────
  ✅  /whoami
       Identifier=123456  UniqueName=20kk99  FirstName=Keshav

──────────────────────────────────────────────────────────
  STEP 3: Enrollments — list your active courses
──────────────────────────────────────────────────────────
  ✅  get_active_courses()
       4 active / 6 total enrollments
       • [12345] CISC 101 (CISC101)
       • [12346] APSC 200 (APSC200)

──────────────────────────────────────────────────────────
  STEP 4: Dropbox folders — list assignments in first course
──────────────────────────────────────────────────────────
  ✅  get_dropbox_folders(12345)
       3 assignment(s) in 'CISC 101'
       • [789] Assignment 1  due=2026-05-15T23:59:00Z

──────────────────────────────────────────────────────────
  STEP 5: Scraper — load the OnQ courses page via Playwright
──────────────────────────────────────────────────────────
  ✅  Playwright headless load
       title='My Home - OnQ'  url=https://onq.queensu.ca/d2l/home
```

### 6. Run the full pipeline

```powershell
# Process all new assignments once:
python -m onq_autopilot.pipeline --once

# Keep polling every 5 minutes:
python -m onq_autopilot.pipeline --watch
```

---

## Troubleshooting

### Step 2 fails (❌ /whoami → 403 or redirect)

> The D2L REST API may require OAuth tokens on OnQ even with browser cookies.

**Fix:** Switch to scraper-only mode.
Tell your agent: *"Step 2 fails with 403 — please implement scraper-only
mode for course/assignment discovery."*

### Step 5 fails (❌ Playwright → landed on login page)

> The browser profile session expired.

**Fix:**
```powershell
Remove-Item .session_state.json
python debug.py   # will re-open browser for fresh login
```

### Session keeps expiring faster than expected

OnQ sessions last ~8–20 hours. `.browser_profile/` preserves the Microsoft
"remember this device" state so MFA is usually skipped on re-login.

---

## What the pipeline does once running

```
For each active course:
  For each dropbox folder (assignment):
    Skip if: already processed | name matches SKIP_TYPES | past due date

    1. Download any instructor-attached files (PDFs, DOCX)
    2. Scrape assignment page for full instructions
    3. Extract text from all files
    4. Build AssignmentBundle → send to LLM
    5. Save answer → outputs/{course_id}/{folder_id}/answer_TIMESTAMP.md
    6. If AUTO_SUBMIT=true: POST answer back to OnQ dropbox
```

Processed assignments tracked in `state/seen.json`.
Delete an entry there to re-process.
