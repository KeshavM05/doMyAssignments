"""
onq_autopilot/latex_output.py
──────────────────────────────
Converts an LLM answer string into a polished LaTeX document,
compiles it to PDF using pdflatex, and saves both files locally.

LaTeX is used because:
  - It produces professional, typeset PDFs
  - Structure (sections, equations, tables) looks far more credible
    than a plain Word export
  - The LLM is instructed to output valid LaTeX directly

Compilation requires a LaTeX installation:
  Windows: MiKTeX  (https://miktex.org/download)
           TeX Live (https://tug.org/texlive/)
  Check:   pdflatex --version

If pdflatex is not found, the .tex file is still saved and a warning
is printed. You can compile it manually later with any LaTeX editor
(Overleaf, TeXstudio, VS Code + LaTeX Workshop).
"""

import os
import re
import subprocess
import shutil
from pathlib import Path
from datetime import datetime

OUTPUT_DIR = Path(os.getenv("OUTPUT_DIR", "outputs"))


# ──────────────────────────────────────────────────────────────────────────────
# LaTeX document wrapper
# ──────────────────────────────────────────────────────────────────────────────

_PREAMBLE = r"""\documentclass[12pt,letterpaper]{article}

% ── Packages ──────────────────────────────────────────────────────────────────
\usepackage[utf8]{inputenc}
\usepackage[T1]{fontenc}
\usepackage{lmodern}
\usepackage[margin=1in]{geometry}
\usepackage{setspace}
\usepackage{parskip}
\usepackage{microtype}
\usepackage{hyperref}
\usepackage{amsmath,amssymb}
\usepackage{booktabs}
\usepackage{graphicx}
\usepackage{enumitem}
\usepackage{fancyhdr}
\usepackage{titlesec}

% ── Typography ─────────────────────────────────────────────────────────────────
\onehalfspacing
\setlength{\parindent}{0pt}
\setlength{\parskip}{8pt}

% ── Header / Footer ───────────────────────────────────────────────────────────
\pagestyle{fancy}
\fancyhf{}
\rhead{\small {course_code}}
\lhead{\small {assignment_name}}
\rfoot{\small Page \thepage}
\renewcommand{\headrulewidth}{0.4pt}

% ── Section formatting ────────────────────────────────────────────────────────
\titleformat{\section}{\large\bfseries}{}{0em}{}[\titlerule]
\titleformat{\subsection}{\normalsize\bfseries}{}{0em}{}

\begin{document}

% ── Title block ───────────────────────────────────────────────────────────────
\begin{center}
  {\LARGE \textbf{{assignment_name}}} \\[6pt]
  {\large {course_name} \quad ({course_code})} \\[4pt]
  {\normalsize Due: {due_date}} \\[2pt]
  {\small \today}
\end{center}

\medskip
\hrule
\bigskip

"""

_POSTAMBLE = r"""
\end{document}
"""


def _escape_latex(text: str) -> str:
    """
    Escape special LaTeX characters in plain-text strings
    (used for metadata fields like course name, not for the body
    which the LLM outputs directly as LaTeX).
    """
    replacements = [
        ("\\", r"\textbackslash{}"),
        ("&",  r"\&"),
        ("%",  r"\%"),
        ("$",  r"\$"),
        ("#",  r"\#"),
        ("_",  r"\_"),
        ("{",  r"\{"),
        ("}",  r"\}"),
        ("~",  r"\textasciitilde{}"),
        ("^",  r"\textasciicircum{}"),
    ]
    for src, dst in replacements:
        text = text.replace(src, dst)
    return text


def wrap_in_document(latex_body: str, bundle: dict) -> str:
    """
    Wrap the LLM-generated LaTeX body in a complete document with
    the course metadata in the header.
    """
    preamble = _PREAMBLE.format(
        course_name    = _escape_latex(bundle.get("course_name", "")),
        course_code    = _escape_latex(bundle.get("course_code", "")),
        assignment_name= _escape_latex(bundle.get("assignment_name", "Assignment")),
        due_date       = _escape_latex(str(bundle.get("due_date") or "Not specified")),
    )

    # Strip any \begin{document} / \end{document} the LLM may have included
    body = re.sub(
        r"\\begin\{document\}|\\end\{document\}|\\documentclass.*?\n",
        "",
        latex_body,
        flags=re.DOTALL,
    )
    # Strip preamble lines the LLM may have emitted
    body = re.sub(r"\\usepackage\{[^}]*\}", "", body)

    return preamble + body.strip() + "\n" + _POSTAMBLE


# ──────────────────────────────────────────────────────────────────────────────
# File I/O
# ──────────────────────────────────────────────────────────────────────────────

def save_latex(latex_source: str, bundle: dict) -> Path:
    """
    Save the full LaTeX document to disk.
    Returns the .tex file path.
    """
    ou_id     = bundle.get("org_unit_id", "unknown")
    folder_id = bundle.get("folder_id",   "unknown")
    out_dir   = OUTPUT_DIR / str(ou_id) / str(folder_id)
    out_dir.mkdir(parents=True, exist_ok=True)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    tex_path  = out_dir / f"answer_{timestamp}.tex"
    tex_path.write_text(latex_source, encoding="utf-8")
    print(f"  [LaTeX] .tex saved → {tex_path}")
    return tex_path


def compile_to_pdf(tex_path: Path) -> Path | None:
    """
    Run pdflatex on the .tex file (twice for proper cross-references).
    Returns the .pdf path on success, or None if pdflatex is not found.

    pdflatex runs in the same directory as the .tex file so relative
    includes (\includegraphics etc.) resolve correctly.
    """
    if not shutil.which("pdflatex"):
        print(
            "  [LaTeX] pdflatex not found. Install MiKTeX or TeX Live to "
            "compile automatically.\n"
            "  You can open the .tex file in Overleaf or any LaTeX editor."
        )
        return None

    tex_dir  = tex_path.parent
    tex_name = tex_path.name

    cmd = [
        "pdflatex",
        "-interaction=nonstopmode",
        "-output-directory", str(tex_dir),
        str(tex_name),
    ]

    for pass_num in (1, 2):
        result = subprocess.run(
            cmd,
            cwd=str(tex_dir),
            capture_output=True,
            text=True,
            timeout=120,
        )
        if result.returncode != 0:
            print(f"  [LaTeX] pdflatex pass {pass_num} failed:")
            # Show last 20 lines of log
            log_lines = (result.stdout + result.stderr).splitlines()
            for line in log_lines[-20:]:
                print(f"    {line}")
            return None

    pdf_path = tex_path.with_suffix(".pdf")
    if pdf_path.exists():
        print(f"  [LaTeX] PDF compiled → {pdf_path}")
        # Clean up auxiliary files
        for ext in (".aux", ".log", ".out"):
            aux = tex_path.with_suffix(ext)
            if aux.exists():
                aux.unlink()
        return pdf_path
    return None


# ──────────────────────────────────────────────────────────────────────────────
# Main entry point
# ──────────────────────────────────────────────────────────────────────────────

def generate_output(latex_body: str, bundle: dict) -> dict:
    """
    Full pipeline: wrap → save .tex → compile to PDF.

    Returns:
      {
        "tex_path": Path,
        "pdf_path": Path | None,
      }
    """
    full_latex = wrap_in_document(latex_body, bundle)
    tex_path   = save_latex(full_latex, bundle)
    pdf_path   = compile_to_pdf(tex_path)
    return {"tex_path": tex_path, "pdf_path": pdf_path}
