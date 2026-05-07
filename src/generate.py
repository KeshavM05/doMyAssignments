"""
generate.py — doMyAssignments core script

Usage:
    python src/generate.py                        # processes all files in assignments/
    python src/generate.py assignments/hw1.pdf    # process a specific file

Output: outputs/YYYY-MM-DD_HH-MM_<filename>.tex
"""

import os
import sys
import json
import boto3
from pathlib import Path
from datetime import datetime
from dotenv import load_dotenv

load_dotenv()

# ── Config ────────────────────────────────────────────────────────────────────

BEDROCK_MODEL  = os.getenv("BEDROCK_MODEL",  "us.anthropic.claude-sonnet-4-6-20251101-v1:0")
BEDROCK_REGION = os.getenv("BEDROCK_REGION", "us-east-1")
STUDENT_NAME   = os.getenv("STUDENT_NAME",   "Keshav Mehndiratta")
STUDENT_ID     = os.getenv("STUDENT_ID",     "20416565")

ROOT       = Path(__file__).parent.parent
STYLE_FILE = ROOT / "style" / "STYLE.md"
ASSIGN_DIR = ROOT / "assignments"
OUTPUT_DIR = ROOT / "outputs"

# ── Style prompt ──────────────────────────────────────────────────────────────

SYSTEM_PROMPT = f"""You are generating a university assignment submission for {STUDENT_NAME} (Student ID: {STUDENT_ID}).

OUTPUT FORMAT
─────────────
Output a COMPLETE, COMPILABLE LaTeX document — from \\documentclass to \\end{{document}}.
Include a cover page exactly like this:

\\begin{{titlepage}}
    \\centering
    \\vspace*{{2in}}
    {{\\Huge \\textbf{{COURSE CODE: Course Name}}}} \\\\
    \\vspace{{0.5in}}
    {{\\LARGE \\textbf{{Assignment \\#N}}}} \\\\
    \\vspace{{1.5in}}
    {{\\Large \\textbf{{{STUDENT_NAME}}}}} \\\\
    \\vspace{{0.2in}}
    {{\\large Student ID: {STUDENT_ID}}} \\\\
    \\vfill
    {{\\large \\today}}
\\end{{titlepage}}

Always use this preamble:
\\documentclass[12pt]{{article}}
\\usepackage{{amsmath, amssymb, geometry, graphicx, float, booktabs, array}}
\\geometry{{a4paper, margin=1in}}
\\setlength{{\\parindent}}{{0pt}}
\\setlength{{\\parskip}}{{0.75em}}

Structure:
- \\section*{{Problem N: Title}} for each problem
- \\subsection*{{(a) Title}} for sub-parts
- \\newpage between major problems

WRITING STYLE
─────────────
- Concise but complete. Answer exactly what is asked, nothing more.
- No fluff. Do not write "In this problem we will..." — just start solving.
- Short declarative sentences for setup. Slightly longer for analysis.
- End each section with a clean one-sentence conclusion where appropriate.
- Confident and direct. "The algorithm converges in 4 iterations." Not "It appears that..."

MATH & TABLES
─────────────
- Standalone equations: \\[ ... \\]
- Inline math: $...$
- Multi-line derivations: align* environment
- Iteration lists: itemize with \\textbf{{Iteration k:}} labels
- Tables: booktabs style (\\toprule, \\midrule, \\bottomrule), [H] float, caption above
- Wide tables: wrap in \\resizebox{{0.95\\textwidth}}{{!}}{{...}}
- Side-by-side tables: minipage at .45\\textwidth with \\hfill between
- Show 4-6 decimal places for iterative/numerical results
- Bold the final answer in tables

BANNED — never use any of these:
- Punctuation: semicolons (;), em dashes (—), ellipses (...)
- Phrases: Furthermore, Moreover, Additionally, In conclusion, It is important to note,
  It is worth noting, Notably, Significantly, This paper will, In summary, In order to
- Words: delve, leverage, robust, comprehensive, multifaceted, utilize, synergy, paradigm
"""


# ── File extraction ───────────────────────────────────────────────────────────

def extract_text(filepath: Path) -> str:
    ext = filepath.suffix.lower()

    if ext == ".pdf":
        import pdfplumber
        text = []
        with pdfplumber.open(filepath) as pdf:
            for page in pdf.pages:
                t = page.extract_text()
                if t:
                    text.append(t)
        return "\n\n".join(text)

    elif ext == ".docx":
        from docx import Document
        doc = Document(filepath)
        return "\n".join(p.text for p in doc.paragraphs if p.text.strip())

    elif ext in (".txt", ".md", ".tex"):
        return filepath.read_text(encoding="utf-8")

    else:
        raise ValueError(f"Unsupported file type: {ext}")


# ── Bedrock call ──────────────────────────────────────────────────────────────

def call_bedrock(assignment_text: str) -> str:
    client = boto3.client("bedrock-runtime", region_name=BEDROCK_REGION)

    user_prompt = f"""Here is the assignment. Complete it fully and return a submission-ready LaTeX document.

ASSIGNMENT CONTENT
──────────────────
{assignment_text}

──────────────────────────────────────────────────────────────────────────────
Return a complete, compilable LaTeX document. Cover page, all problems solved,
proper formatting. Nothing left blank or marked as TODO.
"""

    response = client.converse(
        modelId=BEDROCK_MODEL,
        system=[{"text": SYSTEM_PROMPT}],
        messages=[{"role": "user", "content": [{"text": user_prompt}]}],
        inferenceConfig={
            "maxTokens": 16000,
            "temperature": 0.3,
        },
    )

    return response["output"]["message"]["content"][0]["text"]


# ── Output ────────────────────────────────────────────────────────────────────

def save_output(content: str, source_name: str) -> Path:
    OUTPUT_DIR.mkdir(exist_ok=True)
    timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M")
    stem = Path(source_name).stem
    out_path = OUTPUT_DIR / f"{timestamp}_{stem}.tex"
    out_path.write_text(content, encoding="utf-8")
    return out_path


# ── Main ──────────────────────────────────────────────────────────────────────

def process_file(filepath: Path):
    print(f"  Reading: {filepath.name}")
    text = extract_text(filepath)
    print(f"  Extracted {len(text)} chars — calling Bedrock...")
    latex = call_bedrock(text)
    out = save_output(latex, filepath.name)
    print(f"  Saved → {out.relative_to(ROOT)}")
    return out


def main():
    if len(sys.argv) > 1:
        # Specific file passed as argument
        targets = [Path(sys.argv[1])]
    else:
        # Process everything in assignments/
        ASSIGN_DIR.mkdir(exist_ok=True)
        targets = [
            f for f in ASSIGN_DIR.iterdir()
            if f.is_file() and f.suffix.lower() in (".pdf", ".docx", ".txt", ".md", ".tex")
        ]
        if not targets:
            print(f"No files found in {ASSIGN_DIR}/")
            print("Drop your assignment PDF or DOCX there and re-run.")
            sys.exit(0)

    print(f"\ndoMyAssignments — processing {len(targets)} file(s)\n")
    for f in targets:
        print(f"[{f.name}]")
        try:
            out = process_file(f)
            print(f"  ✅ Done\n")
        except Exception as e:
            print(f"  ❌ Error: {e}\n")

    print("All done. Open outputs/ and drop the .tex file into Overleaf.")


if __name__ == "__main__":
    main()
