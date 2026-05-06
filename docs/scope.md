# ONQ Autopilot — Scope

## In Scope

### Data collection
- Enumerating all active course enrollments via the D2L Valence REST API
- Scraping the Assessments/Assignments tab to find upcoming dropbox folders
- Downloading instructor-attached files (PDFs, DOCX) from the assignment page
- Scraping the Course Content tab to find related assignment briefs or rubrics
- Matching content topics to assignments using fuzzy name similarity
- Extracting text from PDFs, DOCX files, and HTML instruction bodies

### Assignment processing
- Sending the collected context (instructions + files) to a configurable LLM
- Generating a complete, LaTeX-formatted academic answer
- Compiling the LaTeX source to PDF using pdflatex (if installed)
- Saving both the `.tex` source and `.pdf` to a local output directory

### Automation
- One-shot mode: scan all courses once, process new assignments, exit
- Watch mode: poll continuously at a configurable interval
- State tracking: skip assignments already processed

### Configuration
- LLM provider and model selection (OpenAI, Anthropic, Google)
- Assignment name keywords to skip (e.g. "quiz", "exam")
- Output directory location
- Poll interval

## Out of Scope (current version)

### Submission
Auto-submitting answers to OnQ is intentionally excluded. The outputs are for
review only. Submission requires manual action by the user.

### Quiz and exam handling
The D2L Quiz API is a separate system entirely (not dropbox-based). Timed,
proctored assessments are excluded by design and should be added to SKIP_TYPES.

### Course material ingestion beyond direct matches
The pipeline looks for content topics whose names match the assignment. It does
not crawl all course content and build a RAG knowledge base. That is a Phase 5+
feature.

### Multi-user support
The tool uses a single browser session tied to one OnQ account. There is no
user management, no multi-tenancy, and no authentication system beyond the
Playwright cookie flow.

### Notifications
There is no email, Discord, or push notification system. You check the outputs
folder or the CLI output.

### GUI
No web interface exists yet. Everything runs from the command line.

## Future Scope (tracked in roadmap)

| Phase | Feature |
|-------|---------|
| 2 | FastAPI backend to wrap pipeline as HTTP endpoints |
| 3 | React dashboard — assignment queue, answer viewer, approve flow |
| 4 | EC2 deployment with Docker |
| 5 | Browser extension for one-click session refresh |
| 6 | RAG over course notes for richer context |
| 7 | Quiz mode (separate D2L API surface) |
| 8 | Multi-user support |

## Known Constraints

**Session lifetime.** OnQ browser sessions last roughly 8 to 20 hours. The
pipeline detects expiry and re-opens a browser window for you to log in again.
With the persistent `.browser_profile/` directory, Microsoft's "remember this
device" state means MFA is often skipped on re-login.

**LaTeX compilation.** Producing a PDF requires pdflatex (MiKTeX or TeX Live)
to be installed on the machine running the pipeline. If it is not found, the
`.tex` file is still saved and can be compiled manually or uploaded to Overleaf.

**D2L API surface.** The REST API (Valence) is used where possible for
reliability. Where the API does not return sufficient data (e.g., rich
instruction HTML), Playwright scrapes the rendered page. The scraper targets
D2L class names and URL patterns that are stable across OnQ updates but may
require adjustment if D2L makes major UI changes.

**LLM accuracy.** The tool constrains the LLM with detailed writing rules but
cannot guarantee factual accuracy. All outputs require human review before use.
