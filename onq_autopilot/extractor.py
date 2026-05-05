"""
onq_autopilot/extractor.py
──────────────────────────
Extracts clean, structured text from assignment metadata and any
attached files (PDFs, DOCX, plain text, HTML instructions).

Returns an AssignmentBundle — a single dict that gets passed verbatim
to the LLM module.
"""

import os
import re
from html.parser import HTMLParser
from pathlib import Path


# ──────────────────────────────────────────────────────────────────────────────
# HTML → Plain Text
# ──────────────────────────────────────────────────────────────────────────────

class _HTMLTextExtractor(HTMLParser):
    def __init__(self):
        super().__init__()
        self._chunks = []

    def handle_data(self, data):
        stripped = data.strip()
        if stripped:
            self._chunks.append(stripped)

    def get_text(self):
        return "\n".join(self._chunks)


def html_to_text(html: str) -> str:
    parser = _HTMLTextExtractor()
    parser.feed(html or "")
    return parser.get_text()


# ──────────────────────────────────────────────────────────────────────────────
# File content extraction
# ──────────────────────────────────────────────────────────────────────────────

def extract_text_from_file(filepath: str) -> str:
    """
    Dispatch to the right extractor based on file extension.
    Returns plain UTF-8 text.

    Supported: .pdf, .docx, .doc, .txt, .md, .html, .htm
    Unknown types: returns a note that the file couldn't be parsed.
    """
    ext = Path(filepath).suffix.lower()

    if ext == ".pdf":
        return _extract_pdf(filepath)
    elif ext in (".docx", ".doc"):
        return _extract_docx(filepath)
    elif ext in (".txt", ".md"):
        with open(filepath, "r", encoding="utf-8", errors="replace") as f:
            return f.read()
    elif ext in (".html", ".htm"):
        with open(filepath, "r", encoding="utf-8", errors="replace") as f:
            return html_to_text(f.read())
    else:
        return f"[Could not extract text from {Path(filepath).name} — unsupported type {ext}]"


def _extract_pdf(filepath: str) -> str:
    try:
        import pdfplumber
        with pdfplumber.open(filepath) as pdf:
            pages = [page.extract_text() or "" for page in pdf.pages]
        return "\n\n".join(pages)
    except ImportError:
        return "[pdfplumber not installed — run: pip install pdfplumber]"
    except Exception as e:
        return f"[PDF extraction error: {e}]"


def _extract_docx(filepath: str) -> str:
    try:
        import docx
        doc = docx.Document(filepath)
        return "\n".join(p.text for p in doc.paragraphs if p.text.strip())
    except ImportError:
        return "[python-docx not installed — run: pip install python-docx]"
    except Exception as e:
        return f"[DOCX extraction error: {e}]"


# ──────────────────────────────────────────────────────────────────────────────
# Assignment Bundle builder
# ──────────────────────────────────────────────────────────────────────────────

def build_assignment_bundle(
    course: dict,
    folder: dict,
    attachment_paths: list[str],
) -> dict:
    """
    Combines all assignment data into a single structured dict ready
    for the LLM prompt builder.

    Args:
        course:           OrgUnit dict from d2l_client.get_active_courses()
        folder:           DropboxFolder dict from d2l_client.get_dropbox_folders()
        attachment_paths: Local paths to any downloaded instructor attachments

    Returns:
        AssignmentBundle dict:
          {
            "course_name":      str,
            "assignment_name":  str,
            "due_date":         str | None,
            "max_score":        float | None,
            "instructions":     str,         # cleaned HTML → text
            "attachments":      [{"name": str, "text": str}, ...],
            "submission_type":  str,         # "Text" | "File" | "OnPaper" | ...
            "already_submitted": bool,
          }
    """
    instructions_html = ""
    instr = folder.get("CustomInstructions")
    if isinstance(instr, dict):
        instructions_html = instr.get("Html", "") or instr.get("Text", "")
    elif isinstance(instr, str):
        instructions_html = instr

    submission_type_map = {
        "0": "File",
        "1": "Text",
        "2": "OnPaper",
        "3": "Observed",
        "4": "File or Text",
    }
    sub_type_raw = str(folder.get("SubmissionType", "0"))
    submission_type = submission_type_map.get(sub_type_raw, sub_type_raw)

    attachments = []
    for path in attachment_paths:
        attachments.append({
            "name": Path(path).name,
            "text": extract_text_from_file(path),
        })

    return {
        "course_name":       course.get("OrgUnit", {}).get("Name", "Unknown Course"),
        "course_code":       course.get("OrgUnit", {}).get("Code", ""),
        "assignment_name":   folder.get("Name", "Unnamed Assignment"),
        "due_date":          folder.get("DueDate"),
        "max_score":         folder.get("Assessment", {}).get("ScoreDenominator") if folder.get("Assessment") else None,
        "instructions":      html_to_text(instructions_html),
        "attachments":       attachments,
        "submission_type":   submission_type,
        "already_submitted": folder.get("TotalUsersWithSubmissions", 0) > 0,
    }
