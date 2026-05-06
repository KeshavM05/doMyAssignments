# ONQ Autopilot 🎓🤖

> **Automated pipeline:** Polls your Queen's University OnQ (D2L Brightspace)
> account, fetches every new assignment, and uses an LLM to produce a
> submission-ready answer — optionally submitting it automatically.

---

## Table of Contents

1. [Project Overview](#1-project-overview)
2. [Architecture](#2-architecture)
3. [Repository Layout](#3-repository-layout)
4. [D2L / Brightspace API Primer](#4-d2l--brightspace-api-primer)
5. [Authentication Setup (Critical — Read First)](#5-authentication-setup-critical--read-first)
6. [Environment Variables Reference](#6-environment-variables-reference)
7. [Installation](#7-installation)
8. [Running the Pipeline](#8-running-the-pipeline)
9. [Module Reference](#9-module-reference)
10. [LLM Provider Configuration](#10-llm-provider-configuration)
11. [Supported Assignment Types](#11-supported-assignment-types)
12. [State & Output Files](#12-state--output-files)
13. [Extending the Pipeline](#13-extending-the-pipeline)
14. [Known Limitations & Gotchas](#14-known-limitations--gotchas)
15. [Roadmap](#15-roadmap)

---

## 1. Project Overview

| Field | Value |
|-------|-------|
| **Institution** | Queen's University |
| **Platform** | D2L Brightspace (branded as **OnQ**) |
| **Base URL** | `https://onq.queensu.ca` |
| **API** | D2L Valence REST API v1.82 |
| **Auth** | Cookie-based session (Playwright SSO login) |
| **Language** | Python 3.11+ |
| **LLMs** | OpenAI / Anthropic / Google (configurable) |

### What it does

```
OnQ Account
    │
    ▼  (D2L Valence API)
All active courses
    │
    ▼  foreach course
All dropbox (assignment) folders
    │
    ▼  foreach NEW folder
Download instructor attachments (PDFs, DOCX…)
    │
    ▼
Extract clean text from files + HTML instructions
    │
    ▼
Build structured AssignmentBundle
    │
    ▼  (LLM API call)
LLM produces submission-ready answer
    │
    ▼
Save answer to outputs/<course_id>/<folder_id>/answer_TIMESTAMP.md
    │
    ▼  (if AUTO_SUBMIT=true)
POST answer back to D2L dropbox
```

---

## 2. Architecture

```
┌──────────────────────────────────────────────────────────────────┐
│                     pipeline.py (orchestrator)                   │
│  scan_once() / watch()                                           │
│    ├─► d2l_client.get_active_courses()   ← REST API + cookies    │
│    ├─► d2l_client.get_dropbox_folders()  ← REST API + cookies    │
│    ├─► d2l_client.download_folder_attachment()                   │
│    ├─► scraper.scrape_assignment_page()  ← Playwright HTML       │
│    ├─► extractor.build_assignment_bundle()                       │
│    ├─► llm.complete(bundle)                                      │
│    └─► d2l_client.submit_text_submission()  [if enabled]         │
│         OR scraper.submit_via_browser()     [fallback]           │
└──────────────────────────────────────────────────────────────────┘
         │                │               │               │
   session.py       d2l_client.py    scraper.py     extractor.py
  Playwright SSO    Valence REST     Playwright      File parsing
  Cookie persist    API wrappers     HTML scraper    Prompt build
```

### Why cookies instead of OAuth?

D2L Brightspace accepts the **same browser session cookies** for REST API calls
that it sets when you log in through the web interface. This means:

- ✅ No OAuth app registration with IT
- ✅ No API keys from the institution  
- ✅ Uses your real student account
- ✅ Accesses exactly what you can see in the browser
- ⚠️  Sessions expire (~8–20h), requiring a re-login

### Data flow

| Object | Source | Purpose |
|--------|--------|---------|
| Browser cookies | Playwright (one-time login) | Authenticate all API + scrape calls |
| `Enrollment` | REST API `/lp/{v}/enrollments/myenrollments/` | List of courses |
| `DropboxFolder` | REST API `/le/{v}/{orgId}/dropbox/folders/` | Assignment metadata |
| Scraped HTML | Playwright `/d2l/lms/dropbox/user/folder_submit_files.d2l` | Richer instructions |
| File (binary) | REST API `.../attachments/{fileId}` | Instructor PDFs |
| `AssignmentBundle` | Built by `extractor.py` | Sent to LLM |

---

## 3. Repository Layout

```
d2l/
├── .gitignore
├── .env.example          ← Copy to .env and fill in
├── pyproject.toml        ← Dependencies (includes playwright)
├── README.md             ← This file
│
├── onq_autopilot/
│   ├── __init__.py
│   ├── session.py        ← Playwright SSO login, cookie persistence
│   ├── d2l_client.py     ← Valence REST API wrappers (cookie-authed)
│   ├── scraper.py        ← Playwright HTML scraper + browser submitter
│   ├── extractor.py      ← File parsing, AssignmentBundle builder
│   ├── llm.py            ← LLM provider dispatch, prompt builder
│   └── pipeline.py       ← Main orchestration loop (CLI entry-point)
│
├── tests/
│   └── test_extractor.py ← Unit tests (no network)
│
├── state/
│   └── seen.json         ← Processed assignment IDs (auto-created)
│
├── .session_state.json   ← Browser cookies (auto-created, gitignored!)
├── .browser_profile/     ← Chromium profile dir (gitignored!)
│                            (no .tokens.json — OAuth is not used)
│
└── outputs/              ← LLM answers (auto-created, gitignored)
    └── {org_unit_id}/
        └── {folder_id}/
            ├── attachments/
            └── answer_TIMESTAMP.md
```

---

## 4. D2L / Brightspace API Primer

> **Full reference:** https://docs.valence.desire2learn.com/

### Key concepts

| Term | Meaning |
|------|---------|
| **Org Unit** | A course section. Has a numeric `Id`. |
| **Dropbox Folder** | An assignment submission slot. Identified by `Id`. |
| **SubmissionType** | `0=File, 1=Text, 2=OnPaper, 3=Observed, 4=File or Text` |

### Endpoints used

| Method | Path | Purpose |
|--------|------|---------|
| GET | `/d2l/api/lp/1.82/users/whoami` | Verify session / get user ID |
| GET | `/d2l/api/lp/1.82/enrollments/myenrollments/` | List all courses |
| GET | `/d2l/api/le/1.82/{orgId}/dropbox/folders/` | List assignments |
| GET | `/d2l/api/le/1.82/{orgId}/dropbox/folders/{fId}/attachments/{fileId}` | Download instructor file |
| GET | `/d2l/api/le/1.82/{orgId}/dropbox/folders/{fId}/submissions/mysubmissions/` | Check prior submissions |
| POST | `/d2l/api/le/1.82/{orgId}/dropbox/folders/{fId}/submissions/` | Submit text answer |
| GET | `/d2l/lp/auth/xsrf-tokens` | Get CSRF token for POST calls |

---

## 5. Authentication — How the Cookie Approach Works

### First run (visible browser)

```
You                    Playwright              OnQ / Microsoft SSO
 │                         │                          │
 │    python --once         │                          │
 │─────────────────────────►│                          │
 │                          │── opens Chromium ──────►│
 │                          │◄── Microsoft login page ─│
 │◄── browser window ───────│                          │
 │── enter NetID + password ──────────────────────────►│
 │── complete MFA ─────────────────────────────────────►│
 │                          │◄── redirect to OnQ ──────│
 │                          │── save cookies ──────────│
 │                          │   to .session_state.json │
 │◄── browser closes ───────│                          │
 │                          │── continues pipeline ────│
```

### Subsequent runs (headless)

```
pipeline.py → session.get_requests_session()
           → loads .session_state.json
           → hits /whoami → 200 OK → session still valid
           → all API calls use cookie session
           → no browser opens
```

### Session expiry

If the session expires (~8–20h depending on OnQ config), the next run will:
1. Detect the 401 on `/whoami`
2. Open the browser again for you to re-login
3. Save fresh cookies
4. Continue

### MFA handling

- The visible browser is a **real Chromium** with a persistent profile (`.browser_profile/`)
- After the first login + MFA, Microsoft sets a "remember this device" cookie in the profile
- Subsequent re-logins (for expired sessions) often skip MFA entirely
- You do NOT need TOTP codes or anything programmatic

---

## 6. Environment Variables Reference

Copy `.env.example` → `.env` and fill in every value.

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `ONQ_BASE_URL` | No | `https://onq.queensu.ca` | Base URL of your D2L instance |
| `LLM_PROVIDER` | **Yes** | `openai` | `openai` \| `anthropic` \| `google` |
| `OPENAI_API_KEY` | If using OpenAI | — | Your OpenAI key |
| `OPENAI_MODEL` | No | `gpt-4o` | Model name |
| `ANTHROPIC_API_KEY` | If using Anthropic | — | Your Anthropic key |
| `ANTHROPIC_MODEL` | No | `claude-opus-4-5` | Model name |
| `GOOGLE_API_KEY` | If using Google | — | Your Google AI key |
| `GOOGLE_MODEL` | No | `gemini-2.5-pro` | Model name |
| `POLL_INTERVAL_SECONDS` | No | `300` | Seconds between scans in watch mode |
| `SKIP_TYPES` | No | `quiz,exam` | Assignment name keywords to skip |
| `OUTPUT_DIR` | No | `outputs/` | Where to save LLM answers |
| `AUTO_SUBMIT` | No | `false` | **Set true only after manual testing!** |

---

## 7. Installation

```bash
# 1. Clone / enter the repo
cd d:\d2l

# 2. Create a virtual environment
python -m venv .venv
.venv\Scripts\activate          # Windows PowerShell

# 3. Install dependencies
pip install -e ".[dev]"

# 4. Copy and fill in the environment file
copy .env.example .env
# Edit .env with your keys

# 5. Run the tests to verify the extraction layer works
pytest tests/ -v
```

---

## 8. Running the Pipeline

### One-shot scan

```bash
python -m onq_autopilot.pipeline --once
```

First run will open a browser window for you to log in via NetID + MFA.
After login, session cookies are saved to `.session_state.json` and all active courses are
scanned for new assignments.

### Continuous polling

```bash
python -m onq_autopilot.pipeline --watch
```

Polls every `POLL_INTERVAL_SECONDS` seconds. Leave this running in a terminal
or set it up as a scheduled task (see below).

### Windows Task Scheduler (run on startup)

1. Open Task Scheduler → Create Basic Task
2. Trigger: "When I log on"
3. Action: `python -m onq_autopilot.pipeline --watch`
4. Start in: `d:\d2l`

---

## 9. Module Reference

### `onq_autopilot/d2l_client.py`

| Function | Description |
|----------|-------------|
| `get_my_user_id()` | Returns authenticated user's D2L ID. |
| `get_my_enrollments()` | Returns all enrollment objects. |
| `get_active_courses()` | Filtered list of accessible courses. |
| `get_dropbox_folders(org_unit_id)` | All assignment folders for a course. |
| `get_dropbox_folder(org_unit_id, folder_id)` | Single assignment metadata. |
| `get_my_submissions(org_unit_id, folder_id)` | Current user's prior submissions. |
| `download_folder_attachment(org_unit_id, folder_id, file_id, save_path)` | Download instructor file. |
| `submit_text_submission(org_unit_id, folder_id, text_html, comment)` | POST text submission (guarded by AUTO_SUBMIT). |

### `onq_autopilot/extractor.py`

| Function | Description |
|----------|-------------|
| `build_assignment_bundle(course, folder, attachment_paths)` | Returns the `AssignmentBundle` dict. |
| `extract_text_from_file(filepath)` | Dispatches to PDF/DOCX/text parsers. |
| `html_to_text(html)` | Strips HTML tags to plain text. |

### `onq_autopilot/llm.py`

| Function | Description |
|----------|-------------|
| `complete(bundle)` | Routes to the configured LLM provider and returns the answer string. |
| `build_prompt(bundle)` | Constructs the full user-facing prompt from the bundle. |

### `onq_autopilot/pipeline.py`

| Function | Description |
|----------|-------------|
| `scan_once()` | One full scan of all active courses. |
| `watch()` | Infinite polling loop. |
| `process_assignment(course, folder)` | End-to-end handling of a single assignment. |

---

## 10. LLM Provider Configuration

### OpenAI (default)

```env
LLM_PROVIDER=openai
OPENAI_API_KEY=sk-...
OPENAI_MODEL=gpt-4o
```

Best for: general essays, code, structured reports.

### Anthropic Claude

```env
LLM_PROVIDER=anthropic
ANTHROPIC_API_KEY=sk-ant-...
ANTHROPIC_MODEL=claude-opus-4-5
```

Best for: long-form writing, careful reasoning, following complex rubrics.

### Google Gemini

```env
LLM_PROVIDER=google
GOOGLE_API_KEY=...
GOOGLE_MODEL=gemini-2.5-pro
```

Best for: STEM problems, math, science.

---

## 11. Supported Assignment Types

| D2L SubmissionType | Value | Auto-completable | Notes |
|--------------------|-------|-----------------|-------|
| File | 0 | ⚠️ Partial | LLM answer is saved as .md; you still upload manually |
| Text | 1 | ✅ Full | Can POST directly via API |
| OnPaper | 2 | ❌ No | Physical submission — skipped |
| Observed | 3 | ❌ No | In-person observation — skipped |
| File or Text | 4 | ✅ Full | Submits as text via API |

---

## 12. State & Output Files

### `state/seen.json`

Tracks which `{orgUnitId}:{folderId}` pairs have been processed.
Delete an entry to re-process an assignment.

```json
["123:456", "123:789", "987:111"]
```

### `outputs/{orgUnitId}/{folderId}/`

```
outputs/
└── 123456/               ← course org unit ID
    └── 789/              ← folder (assignment) ID
        ├── attachments/
        │   └── brief.pdf  ← downloaded from OnQ
        └── answer_20260505_120000.md  ← LLM response
```

---

## 13. Extending the Pipeline

### Add a new file type parser

In `extractor.py`, add a new branch in `extract_text_from_file()`:

```python
elif ext == ".pptx":
    return _extract_pptx(filepath)
```

### Add a post-processing step (e.g., format as APA essay)

In `pipeline.py`, after `answer = complete(bundle)`, add:

```python
answer = post_process_essay(answer, bundle)
```

### Add a notification (Discord / email)

After `out_file.write_text(...)`, call your notification function:

```python
notify_discord(f"✅ Answer ready for {folder['Name']}: {out_file}")
```

### Swap to a local LLM (Ollama)

Add a new branch in `llm.py`:

```python
elif PROVIDER == "ollama":
    return _ollama(user_prompt)

def _ollama(prompt: str) -> str:
    import requests
    resp = requests.post("http://localhost:11434/api/generate", json={
        "model": os.getenv("OLLAMA_MODEL", "llama3"),
        "prompt": SYSTEM_PROMPT + "\n\n" + prompt,
        "stream": False,
    })
    return resp.json()["response"]
```

---

## 14. Known Limitations & Gotchas

| Issue | Detail |
|-------|--------|
| **Session expiry** | Browser sessions last ~8–20h. Re-login opens the Playwright browser automatically. `.browser_profile/` preserves the Microsoft "remember this device" state so MFA is usually skipped. |
| **API version** | This code targets v1.82. If OnQ upgrades, check the [deprecation notes](https://docs.valence.desire2learn.com/basic/version.html). |
| **Group assignments** | `DropboxType=Group` submissions work differently. The pipeline currently only handles individual submissions. |
| **Quiz/exam detection** | Detection is name-keyword based. It's not foolproof — add more keywords to `SKIP_TYPES`. |
| **Rate limiting** | 429 responses are not retried. Add `time.sleep` + retry logic if needed. |
| **File-type submissions** | The pipeline saves the answer as `.md` but doesn't auto-build a `.docx` for file-only assignments. |
| **LLM accuracy** | The LLM can hallucinate. Always review outputs before submitting. |

---

## 15. Roadmap

- [ ] **Phase 1 (current):** Core pipeline — fetch, extract, LLM, save
- [ ] **Phase 2:** Auto-submission for Text-type assignments with human review step
- [ ] **Phase 3:** DOCX output for File-type assignments (`python-docx`)
- [ ] **Phase 4:** Quiz support (D2L Quiz API is separate — `le/{v}/{orgId}/quizzes/`)
- [ ] **Phase 5:** Notification system (Discord webhook / email)
- [ ] **Phase 6:** Web dashboard (FastAPI + React) showing assignment status
- [ ] **Phase 7:** RAG over course notes / lecture slides for better context
- [ ] **Phase 8:** Multi-user support with per-user token management

---

> ⚠️ **Academic integrity notice:** This tool generates draft responses to
> help you understand and complete assignments. Always review LLM outputs
> critically. You are responsible for the accuracy and originality of
> everything you submit. Check your course syllabus for AI use policies.
