# ONQ Autopilot — Design System

## Guiding Principles

### 1. Boring infrastructure, interesting outputs

The pipeline itself should be invisible. Log lines are clear and emoji-coded
for fast scanning. Errors print enough context to diagnose without overwhelming.
The outputs directory is the product — everything else is plumbing.

### 2. Graceful degradation at every step

Every external call (REST API, Playwright, LLM, pdflatex) can fail. The system
is designed so a failure in one step produces a useful partial result rather
than a crash:

- REST API fails → fall back to browser scraper
- Content match fails → process with instructions only
- pdflatex missing → save `.tex` with instructions to compile manually
- LLM returns invalid LaTeX → save raw output, log the issue

### 3. State is explicit and inspectable

`state/seen.json` is a plain JSON array of strings. You can open it, read it,
and delete entries with a text editor. No opaque database.

### 4. Secrets never touch version control

`.gitignore` excludes: `.env`, `.session_state.json`, `.browser_profile/`,
`outputs/`, `state/`, `*.log`. The repo contains no credentials, no tokens,
and no personal data.

---

## Naming Conventions

### Python modules

All modules are lowercase, underscore-separated:
`session.py`, `d2l_client.py`, `scraper.py`, `extractor.py`,
`llm.py`, `latex_output.py`, `pipeline.py`.

### Functions

Public functions use `snake_case` and are named as verbs:
`get_requests_session()`, `scrape_assignments_list()`,
`find_content_for_assignment()`, `build_assignment_bundle()`,
`compile_to_pdf()`.

Private helpers (module-internal) are prefixed with an underscore:
`_make_context()`, `_check_session()`, `_escape_latex()`.

### Data structures

The central data object is `AssignmentBundle` (a plain `dict`):

```python
{
  "course_name":    str,   # "CISC 101"
  "course_code":    str,   # "CISC101"
  "assignment_name": str,  # "Lab Report 2"
  "due_date":       str | None,
  "max_score":      float | None,
  "instructions":   str,   # plain text from assignment page
  "attachments":    [{"name": str, "text": str}, ...],
  "content_docs":   [{"name": str, "text": str}, ...],
  "submission_type": str,  # "File", "Text", etc.
  "already_submitted": bool,
  "org_unit_id":    int,
  "folder_id":      int,
}
```

Content topic dicts (from scraper):

```python
{
  "topic_id":  int | None,
  "title":     str,
  "type":      str,    # "File/PDF", "File/DOCX", "Link"
  "url":       str,
  "module":    str,    # parent module path
  "score":     float,  # set by find_content_for_assignment()
}
```

### Output files

```
outputs/{org_unit_id}/{folder_id}/
  attachments/{original_filename}       ← instructor dropbox files
  content/content_{topic_id}.{ext}      ← matched course content files
  answer_{YYYYMMDD_HHMMSS}.tex          ← LaTeX source
  answer_{YYYYMMDD_HHMMSS}.pdf          ← compiled PDF
```

State file:

```
state/seen.json   →  ["12345:678", "12345:679", ...]
                      ^orgUnitId  ^folderId
```

---

## Environment Variables

All runtime configuration lives in `.env` (copied from `.env.example`).

| Variable | Type | Default | Description |
|----------|------|---------|-------------|
| `ONQ_BASE_URL` | URL | `https://onq.queensu.ca` | D2L instance base URL |
| `SESSION_FILE` | path | `.session_state.json` | Cookie persistence file |
| `LLM_PROVIDER` | enum | `openai` | `openai` / `anthropic` / `google` |
| `OPENAI_API_KEY` | secret | — | OpenAI API key |
| `OPENAI_MODEL` | string | `gpt-4o` | Model name |
| `ANTHROPIC_API_KEY` | secret | — | Anthropic API key |
| `ANTHROPIC_MODEL` | string | `claude-opus-4-5` | Model name |
| `GOOGLE_API_KEY` | secret | — | Google AI API key |
| `GOOGLE_MODEL` | string | `gemini-2.5-pro` | Model name |
| `POLL_INTERVAL_SECONDS` | int | `300` | Watch mode poll frequency |
| `SKIP_TYPES` | csv | `quiz,exam,midterm,final` | Keywords → skip assignment |
| `OUTPUT_DIR` | path | `outputs/` | Where to save .tex and .pdf |
| `MAX_CONTENT_DOCS` | int | `2` | Max content docs sent to LLM |

---

## LaTeX Document Design

### Typography choices

- `\documentclass[12pt,letterpaper]{article}` — standard North American
  academic format
- `lmodern` — better than the default Computer Modern at screen resolution
- `microtype` — character protrusion and font expansion for better justification
- `setspace` with `\onehalfspacing` — matches most submission requirements
- `parskip` with no indent — cleaner than indented paragraphs for most contexts

### Header / footer

- Left header: assignment name
- Right header: course code
- Right footer: page number
- `\headrulewidth 0.4pt` — subtle separator

### Section formatting

- `\section`: large bold, followed by a horizontal rule (`\titlerule`)
- `\subsection`: normal-size bold, no rule

These are intentionally less ornate than typical LaTeX defaults so the document
reads as a student submission rather than a research paper.

### Banned LaTeX constructs

The LLM is instructed not to emit:

- `\begin{document}` / `\end{document}` (pipeline adds these)
- `\documentclass`, `\usepackage` (pipeline owns the preamble)
- Excessive `\vspace`, `\hspace`, or manual spacing hacks
- `\newpage` inside the body (awkward in assignments)

---

## LLM Prompt Design

### System prompt goals

The system prompt has three jobs:
1. Set the output format (LaTeX body, no preamble)
2. Set the writing register (undergraduate academic, specific constraints)
3. Establish accuracy expectations (hedge uncertainty, no invented citations)

### Banned words rationale

The banned word list targets two classes of text:

**AI tells** — phrases that language models overuse because they appear
frequently in training data and signal "academic writing" to the model, but
which strike human readers as artificial:
- "Furthermore", "Moreover", "Additionally" (filler transitions)
- "It is important to note" (unnecessary hedge)
- "delve", "leverage", "robust", "comprehensive" (overused buzzwords)
- Semicolons (a D2L-specific request — they read as formal/robotic in prose)
- Em dashes (similarly requested — use commas or periods instead)

**Structural tells** — opening and closing formulas that make submissions
obviously template-generated:
- "This paper will argue..."
- "In conclusion..."
- "The purpose of this report is to..."

### Temperature settings

OpenAI: `0.4` — low enough for coherent structure, high enough for
varied phrasing. Higher than `0.3` (used in the old prompt) to reduce
repetitive sentence starts.

Anthropic: uses `max_tokens=8000` — Claude defaults to a lower ceiling
which truncates long assignments.

---

## Error Handling Conventions

Every external call is wrapped in a `try/except`. Failures print a bracketed
tag and a one-line description, then the pipeline continues with whatever
data it has:

```
[SESSION]  — auth layer issues
[CONTENT]  — content API or download failures
[SCRAPER]  — Playwright failures
[LaTeX]    — compilation failures
[ERROR]    — unexpected exceptions in pipeline loop
[SKIP]     — intentionally skipped assignments
[WARN]     — non-fatal anomalies
```

Fatal errors (no valid session, no active courses) print a diagnostic message
and suggest `python debug.py` as the next step.
