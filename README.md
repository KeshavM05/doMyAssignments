# doMyAssignments

Vision-powered university assignment solver. Upload a PDF (or DOCX/TXT), and Claude on AWS Bedrock reads it visually — diagrams, tables, equations and all — then streams back a complete, compilable LaTeX submission.

## Stack

| Layer    | Tech                              |
|----------|-----------------------------------|
| Backend  | FastAPI + uvicorn                 |
| LLM      | AWS Bedrock (`converse_stream`)   |
| PDF      | `pdf2image` (poppler) — vision    |
| Frontend | React 18 + Vite + Monaco Editor   |

---

## Quick Start

### 1. AWS credentials

Make sure your AWS credentials are configured (the usual `~/.aws/credentials` or environment variables). The IAM role/user needs `bedrock:InvokeModel` on the model you've configured.

### 2. Environment

```bash
cp .env.example .env
# Edit .env if you need a different model or region
```

### 3. Backend

```bash
cd backend
pip install -r requirements.txt
uvicorn main:app --reload
# → http://localhost:8000
```

> **Poppler required** for PDF vision processing:
> - macOS: `brew install poppler`
> - Ubuntu/Debian: `sudo apt-get install poppler-utils`
> - Windows: download from https://github.com/oschwartz10612/poppler-windows/releases

### 4. Frontend

```bash
cd frontend
npm install
npm run dev
# → http://localhost:5173
```

The Vite dev server proxies `/api` to `http://localhost:8000` automatically.

---

## API Reference

| Method | Path                     | Description                                    |
|--------|--------------------------|------------------------------------------------|
| POST   | `/api/upload`            | Upload files → returns `job_id`                |
| POST   | `/api/generate/{job_id}` | Stream LaTeX output as SSE                     |
| GET    | `/api/jobs`              | List all jobs                                  |
| GET    | `/api/jobs/{job_id}`     | Get single job status                          |
| GET    | `/api/output/{job_id}`   | Download the generated `.tex` file             |
| GET    | `/api/health`            | Health check                                   |

### SSE stream format

```
data: <latex chunk>\n\n
...
data: [DONE]\n\n
```

On error:
```
data: [ERROR] <message>\n\n
```

---

## Supported file types

| Extension | Processing method                        |
|-----------|------------------------------------------|
| `.pdf`    | Vision — pages rendered as PNG images   |
| `.docx`   | Text extraction via `python-docx`        |
| `.txt`    | Direct read                              |
| `.md`     | Direct read                              |

---

## Directory layout

```
doMyAssignments/
├── backend/
│   ├── main.py          # FastAPI app + all endpoints
│   ├── generate.py      # LLM logic, file processing, Bedrock streaming
│   ├── requirements.txt
│   └── uploads/         # Uploaded files (gitignored)
├── frontend/
│   ├── src/
│   │   ├── App.jsx      # Single-page app
│   │   ├── App.css      # Dark theme styles
│   │   └── main.jsx     # Entry point
│   ├── index.html
│   ├── package.json
│   └── vite.config.js   # Dev server + /api proxy
├── style/
│   ├── STYLE.md         # Writing style guide
│   └── TEMPLATE.tex     # LaTeX template reference
├── outputs/             # Generated .tex files (gitignored)
├── assignments/         # Input files (gitignored)
├── .env.example
├── .gitignore
└── README.md
```

---

## Notes

- **No database** — jobs are stored in memory. Restart the backend and history clears.
- **Vision model** — PDFs are sent as images so Claude can see figures, diagrams, hand-drawn tables, etc.
- The generated `.tex` files land in `outputs/` and are downloadable via the UI or `/api/output/{job_id}`.
- Drop the `.tex` into [Overleaf](https://overleaf.com) to compile.

---

*Keshav Mehndiratta · Student ID: 20416565*
