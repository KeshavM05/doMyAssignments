# ONQ Autopilot — Architecture

## System Overview

```
┌─────────────────────────────────────────────────────────────────┐
│                      pipeline.py                                │
│                   (orchestration layer)                         │
│                                                                 │
│   scan_once() / watch()                                         │
│     ├─► d2l_client      GET /enrollments  →  active courses     │
│     │                                                           │
│     └─► per course:                                             │
│           ├─► scraper   Assessments tab  →  assignment list     │
│           ├─► scraper   Contents API     →  content topic tree  │
│           ├─► scraper   fuzzy match      →  best content docs   │
│           ├─► d2l_client download        →  instructor files    │
│           ├─► extractor                  →  text from files     │
│           ├─► llm       prompt + call    →  LaTeX body          │
│           └─► latex_output               →  .tex + .pdf saved  │
└─────────────────────────────────────────────────────────────────┘
        │              │              │              │
  session.py    d2l_client.py    scraper.py    extractor.py
  (auth)        (REST API)       (browser)     (file parse)

                                              llm.py
                                         (LLM dispatch)

                                         latex_output.py
                                         (TeX compile)
```

## Authentication Layer (`session.py`)

D2L Brightspace accepts browser session cookies for REST API calls. There is no
OAuth registration required. The flow:

1. First run: Playwright opens a real Chromium window. You log in through
   Queen's Microsoft SSO and complete MFA. Playwright captures all cookies and
   saves them to `.session_state.json`.

2. Subsequent runs: The saved cookies are loaded into a `requests.Session`.
   A call to `/d2l/api/lp/1.82/users/whoami` verifies the session is still
   alive. If it is, the pipeline continues headlessly with no browser.

3. Session expiry: If `/whoami` returns non-200, Playwright re-opens the
   browser. The persistent `.browser_profile/` directory preserves Microsoft's
   "remember this device" state, so MFA is usually skipped.

4. Module-level cache: `_cached_session` stores the validated `requests.Session`
   for the lifetime of the process, so `/whoami` is only called once per run.

## API Client (`d2l_client.py`)

Wraps the D2L Valence REST API (v1.82). All calls use the cookie-authenticated
`requests.Session` from `session.py`. No OAuth tokens, no `Authorization:
Bearer` headers — the cookies handle everything.

Key endpoints used:

| Endpoint | Purpose |
|----------|---------|
| `GET /lp/1.82/users/whoami` | Session validation |
| `GET /lp/1.82/enrollments/myenrollments/` | Course list |
| `GET /le/1.82/{ou}/dropbox/folders/` | Assignment folders |
| `GET /le/1.82/{ou}/dropbox/folders/{id}` | Single folder metadata |
| `GET /le/1.82/{ou}/dropbox/folders/{id}/attachments/{fid}` | Download file |
| `GET /le/1.82/{ou}/content/toc` | Course content TOC |
| `GET /le/1.82/{ou}/content/topics/{tid}/file` | Download content file |

## Scraper (`scraper.py`)

Playwright-based. Used for two things the REST API does not expose cleanly:

**1. Assignments list** — navigates to the Assessments/Assignments tab:
```
URL: /d2l/lms/dropbox/user/folders_list.d2l?ou={ou}
```
Finds all `<a href*="folder_submit_files.d2l">` links, extracts the folder ID
from the `?db=` query param, reads the surrounding table row for due date and
status, then opens each assignment detail page to get the full instructions.

**2. Course content tree (fallback)** — navigates to:
```
URL: /d2l/le/content/{ou}/Home
```
Used only if the API content TOC call fails. Extracts all topic links by
looking for `<a>` tags with `.pdf`, `.docx`, or `/content/` in their href.

**Content matching** — `find_content_for_assignment()` uses:
- `difflib.SequenceMatcher` for string similarity between assignment name
  and topic title
- A keyword boost (+0.20) if the topic title contains "brief", "rubric",
  "specification", "handout", or similar
- A word overlap boost (+up to 0.15) for shared words between the names
- Topics must be file-type (PDF or DOCX) and score above a threshold (0.45)

## Extractor (`extractor.py`)

Converts local files to plain text for inclusion in the LLM prompt:

| Extension | Library | Notes |
|-----------|---------|-------|
| `.pdf` | pdfplumber | Page-by-page text extraction |
| `.docx` | python-docx | Paragraph-by-paragraph |
| `.txt`, `.md` | built-in | Direct read |
| `.html`, `.htm` | html.parser | Tag-stripped text |
| Other | — | Returns a note explaining failure |

Also builds the `AssignmentBundle` dict that standardises all collected data
into a single structure passed to the LLM.

## LLM Layer (`llm.py`)

### Prompt structure

```
% Course / assignment metadata (as LaTeX comments)
ASSIGNMENT INSTRUCTIONS
───────────────────────
<scraped text from assignment detail page>

ATTACHED DOCUMENT: <filename>
────────────────────────────
<extracted text from instructor PDF>

COURSE CONTENT DOCUMENT: <filename>
────────────────────────────────────
<extracted text from matched content topic>

────────────────────────────────────────────────────
Write a complete, submission-ready answer. Output valid LaTeX body only.
```

### System prompt constraints

The system prompt instructs the LLM to:
- Output LaTeX body only (no preamble, no `\begin{document}`)
- Write like a capable undergraduate, not a language model
- Never use semicolons, em dashes, or ellipses
- Never use flagged transition words or AI-associated vocabulary
- Use APA 7th in-text citations where applicable
- Hedge uncertain claims rather than inventing detail

### Provider dispatch

The `LLM_PROVIDER` env variable selects between OpenAI, Anthropic, and Google.
Each uses the provider's official Python SDK with identical prompt content.

## LaTeX Output (`latex_output.py`)

### Document structure

```latex
\documentclass[12pt,letterpaper]{article}
% packages: geometry, setspace, parskip, microtype,
%           hyperref, amsmath, booktabs, fancyhdr, titlesec
\begin{document}
  % title block: assignment name, course, due date, \today
  % ── LLM body here ──
\end{document}
```

### Compilation

1. `wrap_in_document()` strips any preamble the LLM may have emitted and
   wraps the body in the standard document template.
2. `save_latex()` writes the full source to
   `outputs/{ou}/{folder}/answer_{timestamp}.tex`.
3. `compile_to_pdf()` calls `pdflatex -interaction=nonstopmode` twice (second
   pass resolves cross-references). Auxiliary files (`.aux`, `.log`, `.out`)
   are cleaned up.
4. If `pdflatex` is not in PATH, the `.tex` file is still saved with a message
   pointing the user to MiKTeX or Overleaf.

## Data Flow Summary

```
OnQ portal (browser login)
      │
      ▼ cookies → .session_state.json
requests.Session (cookie-authed)
      │
      ├─► REST API calls ──────────────────► course list, folder metadata, file downloads
      │
      └─► Playwright browser ──────────────► assignment instructions, content topics
              │
              ▼
        AssignmentBundle dict
        {
          course_name, course_code,
          assignment_name, due_date, max_score,
          instructions,       ← scraped text from assignment page
          attachments[],      ← instructor dropbox files
          content_docs[],     ← matched course content files
          submission_type,
          org_unit_id, folder_id
        }
              │
              ▼
        LLM API call → LaTeX body string
              │
              ▼
        pdflatex → outputs/{ou}/{folder}/answer_{ts}.pdf
                                                answer_{ts}.tex
```

## File & Directory Layout

```
d:\d2l\
├── debug.py                     ← connection tester (run first)
├── pyproject.toml               ← Python dependencies
├── .env                         ← secrets (gitignored)
├── .env.example                 ← template
│
├── onq_autopilot/
│   ├── __init__.py
│   ├── session.py               ← Playwright SSO + cookie persistence
│   ├── d2l_client.py            ← Valence REST API wrappers
│   ├── scraper.py               ← Playwright HTML scraper + content matcher
│   ├── extractor.py             ← PDF/DOCX/HTML text extraction
│   ├── llm.py                   ← LLM dispatch + prompt builder
│   ├── latex_output.py          ← LaTeX wrapping + pdflatex compilation
│   └── pipeline.py              ← Orchestration (--once / --watch)
│
├── docs/                        ← This documentation suite
│   ├── vision.md
│   ├── scope.md
│   ├── architecture.md          ← This file
│   ├── design_system.md
│   └── implementation.md
│
├── state/
│   └── seen.json               ← processed assignment IDs
│
├── outputs/                    ← generated .tex and .pdf files (gitignored)
│   └── {org_unit_id}/
│       └── {folder_id}/
│           ├── attachments/    ← instructor dropbox files
│           ├── content/        ← matched course content files
│           ├── answer_*.tex
│           └── answer_*.pdf
│
├── .session_state.json         ← browser cookies (gitignored)
└── .browser_profile/           ← Chromium persistent profile (gitignored)
```
