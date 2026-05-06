# ONQ Autopilot — Implementation

## Current State (v0.2.0)

The pipeline is fully implemented as a local CLI tool. All core modules are
complete and committed to the `master` branch.

### Git history

```
ee9f48a  docs: add RUNNING.md first-run guide
ab072b8  fix: remove stale auth.py, improve session caching, add debug.py
5c897d5  refactor: replace OAuth2 with Playwright cookie-based session
c063a73  feat: initial ONQ Autopilot scaffold
```

---

## Module Implementation Status

### `session.py` ✅ Complete

Handles all authentication. Key implementation details:

- `_BROWSER_DATA_DIR = Path(".browser_profile")` — persistent Chromium profile
  so Microsoft's "remember this device" cookie survives re-logins.
- `_cached_session` — module-level variable holds the validated
  `requests.Session` for the process lifetime. Only calls `/whoami` once.
- `get_requests_session()` — the single public entry point. Checks cache,
  then disk, then triggers browser login as needed.
- `invalidate_session()` — helper to force a fresh login on next call.

```python
# Usage everywhere:
from .session import get_requests_session
s = get_requests_session()
resp = s.get(url)
```

---

### `d2l_client.py` ✅ Complete

All endpoints use `get_requests_session()`. CSRF token is fetched from
`/d2l/lp/auth/xsrf-tokens` before POST calls (required by D2L for
state-mutating operations).

```python
def _get(path: str, **kwargs):
    s = get_requests_session()
    resp = s.get(f"{BASE_URL}/d2l/api/{path}", **kwargs)
    resp.raise_for_status()
    return resp.json()
```

The `submit_text_submission()` function remains in the module (in case it is
needed later) but will raise `PermissionError` because `AUTO_SUBMIT` is not
set. Nothing in the current pipeline calls it.

---

### `scraper.py` ✅ Complete

Three responsibilities, each implemented:

**1. `scrape_assignments_list(org_unit_id)`**

Navigates to `/d2l/lms/dropbox/user/folders_list.d2l?ou={ou}`.
Finds assignment links with `a[href*="folder_submit_files.d2l"]`.
Extracts folder ID from the `?db=` query param.
Opens each assignment detail page and tries a chain of selectors for the
instructions:

```python
selectors = [
    ".d2l-htmleditor-readonly",
    "[data-test-id='dropbox-folder-description']",
    ".dco-assignment-description",
    ".d2l-editor",
    ".d2l-le-scrollable",
    "d2l-html-block",
]
```

Falls through the chain and returns the first non-empty result.

**2. `scrape_course_content_via_api(org_unit_id)`**

Primary method. Calls `GET /d2l/api/le/{v}/{ou}/content/toc` which returns
a nested JSON structure of modules and topics. `_flatten_toc()` recursively
walks this tree into a flat list.

Falls back to `scrape_course_content_via_browser()` if the API call fails.

**3. `find_content_for_assignment(assignment_name, topics, threshold=0.45)`**

Scoring formula per topic:

```
base_score  = SequenceMatcher(assignment_name, topic_title).ratio()
keyword_boost = +0.20 if topic title contains brief/rubric/spec/handout/etc.
word_overlap_boost = (shared_words / assignment_words) * 0.15
final_score = min(base_score + keyword_boost + word_overlap_boost, 1.0)
```

Only file-type topics (PDF, DOCX) above the threshold are returned,
sorted by score descending.

---

### `extractor.py` ✅ Complete (from v0.1.0, unchanged)

Dispatches on file extension:

```python
def extract_text_from_file(filepath: str) -> str:
    ext = Path(filepath).suffix.lower()
    if ext == ".pdf":   return _extract_pdf(filepath)
    if ext == ".docx":  return _extract_docx(filepath)
    if ext in (".txt", ".md"): ...
    if ext in (".html", ".htm"): ...
    return f"[Could not extract text from {ext} file]"
```

`build_assignment_bundle()` takes the raw API folder dict and normalises it:

```python
bundle = {
    "course_name":       course["OrgUnit"]["Name"],
    "course_code":       course["OrgUnit"].get("Code", ""),
    "assignment_name":   folder["Name"],
    "due_date":          folder.get("DueDate"),
    "max_score":         (folder.get("Assessment") or {}).get("ScoreDenominator"),
    "instructions":      html_to_text(instr_html) or instr_text,
    "attachments":       [],   # populated by pipeline
    "submission_type":   SUBMISSION_TYPE_MAP.get(folder["SubmissionType"], "Unknown"),
    "already_submitted": folder.get("TotalUsersWithSubmissions", 0) > 0,
}
```

---

### `llm.py` ✅ Complete

The system prompt is the most important piece. It lives in `SYSTEM_PROMPT` as a
module-level string constant. Key design choices:

- **LaTeX body only.** The prompt explicitly says "no preamble, no
  `\begin{document}`" to prevent the LLM from generating a full document that
  then conflicts with the wrapper the pipeline adds.
- **Banned word list.** Embedded directly in the system prompt so the LLM sees
  it on every call. Includes both punctuation (semicolons, em dashes) and
  vocabulary.
- **`temperature=0.4`** for OpenAI — higher than the previous `0.3` to improve
  sentence-level variation without losing structural coherence.
- **`max_tokens=8000`** across all providers — long enough for a 2000-word
  academic assignment with LaTeX formatting overhead.

---

### `latex_output.py` ✅ Complete

The preamble template in `_PREAMBLE` uses Python `str.format()` with named
placeholders (`{course_code}`, `{assignment_name}`, etc.). Metadata values
are run through `_escape_latex()` before insertion.

The LLM body is cleaned before wrapping:

```python
body = re.sub(
    r"\\begin\{document\}|\\end\{document\}|\\documentclass.*?\n",
    "",
    latex_body,
    flags=re.DOTALL,
)
body = re.sub(r"\\usepackage\{[^}]*\}", "", body)
```

`compile_to_pdf()` checks `shutil.which("pdflatex")` before attempting
compilation. It runs two passes (required for ToC and cross-references) and
cleans up `.aux`, `.log`, `.out` files on success.

---

### `pipeline.py` ✅ Complete

The main loop in `scan_once()`:

```
get_active_courses()          ← REST API
  └─ per course:
       scrape_assignments_list()          ← Playwright
         └─ per assignment (not in seen.json):
              get_dropbox_folder()        ← REST API (metadata + attachments)
              scrape_course_content_via_api()  ← REST API with browser fallback
              find_content_for_assignment()    ← local scoring
              download_topic_file()       ← REST API (up to MAX_CONTENT_DOCS)
              build_assignment_bundle()   ← extractor.py
              complete(bundle)            ← llm.py
              generate_output(body, bundle)   ← latex_output.py
              mark_seen(key)             ← state/seen.json
```

---

## Dependency Installation

```powershell
cd d:\d2l
python -m venv .venv
.venv\Scripts\activate
pip install -e .
playwright install chromium
```

For LaTeX compilation (optional — needed for PDF output):

- **Windows:** Download and install MiKTeX from https://miktex.org/download
  MiKTeX installs `pdflatex` and can auto-install missing packages.
- **Verify:** `pdflatex --version` in PowerShell

---

## Running the Pipeline

```powershell
# Test all layers first:
python debug.py

# Process all new assignments once:
python -m onq_autopilot.pipeline --once

# Keep watching:
python -m onq_autopilot.pipeline --watch
```

---

## Known Implementation Issues / TODOs

| Issue | Status | Notes |
|-------|--------|-------|
| Due date from Assessments tab is a display string, not ISO | Known | Skip date filtering for now; add ISO parse if needed |
| Selector chain in `_scrape_assignment_detail()` may miss D2L Lit components | Known | Add `d2l-html-block` shadow DOM piercing if needed |
| `MAX_CONTENT_DOCS` defaults to 2 — might miss relevant docs | Tunable | Increase in `.env` if needed |
| No retry on transient network errors | TODO | Add `tenacity` retries for REST calls |
| No test coverage for scraper or pipeline modules | TODO | Requires VCR cassettes or a mock D2L server |

---

## Planned Phases

### Phase 2 — FastAPI backend

Wrap pipeline functions as HTTP endpoints:

```
POST /api/cookies        ← receive cookies from bookmarklet
GET  /api/assignments    ← list all assignments + status
POST /api/run/{folder_id} ← trigger processing for one assignment
GET  /api/output/{folder_id} ← download .pdf / .tex
```

Add SQLite via SQLModel for job state (queued / processing / done / error).

### Phase 3 — React dashboard

Single-page app (Vite + React):
- Dashboard: assignment queue with status indicators
- Assignment detail: instructions + editable LLM answer + PDF viewer
- Connect page: bookmarklet flow for cookie injection
- Settings: LLM provider, skip words, poll interval

### Phase 4 — Docker + EC2

```dockerfile
FROM python:3.12-slim
RUN apt-get install -y texlive-latex-base texlive-fonts-recommended
RUN playwright install chromium --with-deps
```

Cloudflare Pages serves the React build. EC2 t3.micro runs the FastAPI
container. Nginx reverse proxy on port 80/443.

### Phase 5 — Browser extension

Chrome extension replaces the bookmarklet. Automatically detects when you are
on an OnQ page, extracts cookies, and sends them to the backend — no manual
steps required for session refresh.
