# doMyAssignments

Automates university assignments. Drop files in, get a submission-ready LaTeX document out.

## What it does

1. You put your assignment files (PDF, DOCX, or plain text) into `assignments/`
2. Run the script
3. Get a `.tex` file in `outputs/` that matches your personal writing style
4. Drop it in Overleaf, submit

## Stack

- **Backend:** Python + boto3 (AWS Bedrock / Claude)
- **Frontend:** React + FastAPI (Phase 2)
- **Output:** LaTeX document compiled to PDF

## Project Structure

```
doMyAssignments/
├── assignments/        ← drop your assignment files here
├── outputs/            ← generated .tex files land here
├── style/
│   ├── STYLE.md        ← writing style rules (your voice)
│   └── TEMPLATE.tex    ← base LaTeX template
├── src/
│   └── generate.py     ← core script (Phase 1)
├── .env.example
├── .gitignore
└── README.md
```

## Setup

```bash
python -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env        # configure AWS region
```

AWS credentials must be configured (`aws configure` or existing `~/.aws/credentials`).

## Usage (Phase 1 — CLI)

```bash
# Drop assignment files into assignments/
python src/generate.py

# Or point at a specific file
python src/generate.py assignments/elec372_a7.pdf
```

Output saved to `outputs/YYYY-MM-DD_HH-MM_<filename>.tex`

## Roadmap

| Phase | Status | Description |
|-------|--------|-------------|
| 1 | 🔨 Building | Core script — file in, `.tex` out |
| 2 | 📋 Planned | FastAPI backend + React frontend |
| 3 | 📋 Planned | Live LaTeX preview (Overleaf-style) |
| 4 | 📋 Planned | Drag & drop UI, inline editing, PDF download |
| 5 | 📋 Planned | D2L/OnQ scraping (auto-fetch assignments) |

## Output Style

Every generated document follows Keshav's personal style:
- Cover page with course, assignment number, name, student ID
- Clean section/subsection structure
- `booktabs` tables, proper math environments
- No semicolons, no em dashes, no AI filler phrases
- Concise and direct — answers what's asked, nothing more

See `style/STYLE.md` for the full style guide.
