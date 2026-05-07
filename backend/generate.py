"""
generate.py — doMyAssignments backend LLM logic (vision-based)

Processes PDF (via vision), DOCX (text extraction), TXT/MD (direct read).
Calls AWS Bedrock converse API with image content blocks for PDFs.
"""

import io
import os
import boto3
from pathlib import Path
from dotenv import load_dotenv

load_dotenv(dotenv_path=Path(__file__).parent.parent / ".env")
load_dotenv(dotenv_path=Path(__file__).parent / ".env")

# ── Config ─────────────────────────────────────────────────────────────────

BEDROCK_MODEL  = os.getenv("BEDROCK_MODEL",  "us.anthropic.claude-sonnet-4-6-20251101-v1:0")
BEDROCK_REGION = os.getenv("BEDROCK_REGION", "us-east-1")
STUDENT_NAME   = os.getenv("STUDENT_NAME",   "Keshav Mehndiratta")
STUDENT_ID     = os.getenv("STUDENT_ID",     "20416565")

# ── System prompt ──────────────────────────────────────────────────────────

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
- No fluff. Do not write "In this problem we will..." just start solving.
- Short declarative sentences for setup. Slightly longer for analysis.
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
  Notably, Significantly, This paper will, In summary, In order to
- Words: delve, leverage, robust, comprehensive, multifaceted, utilize, synergy, paradigm
"""


# ── File processing ────────────────────────────────────────────────────────

def pdf_to_image_blocks(filepath: str) -> list:
    """Convert PDF pages to Bedrock image content blocks via vision."""
    from pdf2image import convert_from_path
    pages = convert_from_path(filepath, dpi=150)
    blocks = []
    for page in pages:
        buf = io.BytesIO()
        page.save(buf, format="PNG")
        blocks.append({
            "image": {
                "format": "png",
                "source": {"bytes": buf.getvalue()}
            }
        })
    return blocks


def docx_to_text(filepath: str) -> str:
    """Extract text from a DOCX file."""
    from docx import Document
    doc = Document(filepath)
    return "\n".join(p.text for p in doc.paragraphs if p.text.strip())


def txt_to_text(filepath: str) -> str:
    """Read a plain text or markdown file."""
    with open(filepath, "r", encoding="utf-8") as f:
        return f.read()


def build_content_blocks(filepath: str) -> tuple[list, str]:
    """
    Returns (image_blocks, text_content) depending on file type.
    For PDFs: image_blocks contains vision blocks, text_content is empty.
    For DOCX/TXT: image_blocks is empty, text_content has the extracted text.
    """
    ext = Path(filepath).suffix.lower()
    if ext == ".pdf":
        blocks = pdf_to_image_blocks(filepath)
        return blocks, ""
    elif ext == ".docx":
        text = docx_to_text(filepath)
        return [], text
    elif ext in (".txt", ".md", ".tex"):
        text = txt_to_text(filepath)
        return [], text
    else:
        raise ValueError(f"Unsupported file type: {ext}")


# ── Bedrock — non-streaming (for fallback / testing) ──────────────────────

def call_bedrock_vision(file_blocks: list, text_content: str = "") -> str:
    """Call Bedrock with vision blocks and/or text content. Returns full response."""
    client = boto3.client("bedrock-runtime", region_name=BEDROCK_REGION)
    content = list(file_blocks)
    if text_content:
        content.append({"text": f"Here is the assignment content:\n\n{text_content}"})
    content.append({
        "text": (
            "Complete this assignment fully. Return a complete compilable LaTeX document. "
            "Cover page, all problems solved, proper formatting. Nothing left blank."
        )
    })

    response = client.converse(
        modelId=BEDROCK_MODEL,
        system=[{"text": SYSTEM_PROMPT}],
        messages=[{"role": "user", "content": content}],
        inferenceConfig={"maxTokens": 16000, "temperature": 0.3},
    )
    return response["output"]["message"]["content"][0]["text"]


# ── Bedrock — streaming ────────────────────────────────────────────────────

def stream_bedrock_vision(file_blocks: list, text_content: str = ""):
    """
    Generator that streams text chunks from Bedrock converse_stream.
    Yields str chunks as they arrive.
    """
    client = boto3.client("bedrock-runtime", region_name=BEDROCK_REGION)
    content = list(file_blocks)
    if text_content:
        content.append({"text": f"Here is the assignment content:\n\n{text_content}"})
    content.append({
        "text": (
            "Complete this assignment fully. Return a complete compilable LaTeX document. "
            "Cover page, all problems solved, proper formatting. Nothing left blank."
        )
    })

    response = client.converse_stream(
        modelId=BEDROCK_MODEL,
        system=[{"text": SYSTEM_PROMPT}],
        messages=[{"role": "user", "content": content}],
        inferenceConfig={"maxTokens": 16000, "temperature": 0.3},
    )

    stream = response.get("stream")
    if not stream:
        return

    for event in stream:
        if "contentBlockDelta" in event:
            delta = event["contentBlockDelta"].get("delta", {})
            text = delta.get("text", "")
            if text:
                yield text
        elif "messageStop" in event:
            break
