"""
onq_autopilot/llm.py
─────────────────────
Routes an AssignmentBundle to the configured LLM and returns a
complete LaTeX document body (everything between \\begin{document}
and \\end{document}).

The prompt is engineered to produce:
  - Valid LaTeX (sections, subsections, itemize, equations as needed)
  - Human-sounding academic writing — varied sentence rhythm, natural
    transitions, no AI clichés
  - No semicolons, no em dashes, no filler phrases

Banned language list (enforced in system prompt):
  Punctuation : semicolons (;), em dashes (—), ellipses (...)
  Transitions : "Furthermore", "Moreover", "Additionally", "In conclusion",
                "It is important to note", "It is worth noting",
                "Notably", "Significantly"
  AI tells    : "delve", "leverage", "robust", "comprehensive",
                "multifaceted", "nuanced", "It's worth", "deep dive",
                "in the realm of", "as an AI"

Supported providers (set LLM_PROVIDER in .env):
  openai | anthropic | google
"""

import os
from dotenv import load_dotenv

load_dotenv()

PROVIDER        = os.getenv("LLM_PROVIDER", "openai").lower()
OPENAI_MODEL    = os.getenv("OPENAI_MODEL",    "gpt-4o")
ANTHROPIC_MODEL = os.getenv("ANTHROPIC_MODEL", "claude-opus-4-5")
GOOGLE_MODEL    = os.getenv("GOOGLE_MODEL",    "gemini-2.5-pro")


# ──────────────────────────────────────────────────────────────────────────────
# System prompt
# ──────────────────────────────────────────────────────────────────────────────

SYSTEM_PROMPT = r"""You are a graduate-level academic writer helping a university student
complete an assignment. Your output will be compiled directly by pdflatex,
so it must be valid LaTeX.

OUTPUT FORMAT
─────────────
Output ONLY the body content — everything that would go between
\begin{document} and \end{document}. Do NOT include \documentclass,
\usepackage, \begin{document}, or \end{document}. The pipeline adds
those automatically.

Structure the answer using:
  \section{...}        for major sections
  \subsection{...}     for subsections
  \begin{itemize}      for bullet lists
  \begin{enumerate}    for numbered lists
  \begin{equation}     for standalone math
  $...$                for inline math
  \textbf{...}         for emphasis (sparingly)
  \begin{table}        for tables with \toprule, \midrule, \bottomrule

WRITING STYLE
─────────────
Write like a sharp, confident undergraduate who reads widely and thinks
clearly. Use:
  - Varied sentence lengths. Short sentences for emphasis. Longer ones
    to build an argument or walk through evidence step by step.
  - Specific examples and data rather than vague generalities.
  - Direct claims. State what is true, then explain why.
  - Contractions only where they sound completely natural in academic
    prose (they usually do not — err on the side of formal).
  - Paragraph breaks that reflect logical shifts, not arbitrary spacing.

BANNED WORDS AND PATTERNS — never use any of these:
  Punctuation : semicolons (;) | em dashes (—) | ellipses (...)
  Phrases     : Furthermore | Moreover | Additionally | In conclusion |
                It is important to note | It is worth noting |
                Notably | Significantly | This paper will | This report will |
                The purpose of this | In summary | To summarize |
                In order to | Due to the fact that
  Vocabulary  : delve | leverage | robust | comprehensive | multifaceted |
                nuanced | synergy | paradigm | holistic | utilize (use "use")

CITATIONS
─────────
Use APA 7th edition in-text citations: (Author, Year).
Add a References section at the end if you cite anything.
Do not invent sources. If you use general knowledge, say so or omit
the citation.

ACCURACY
────────
Do not fabricate facts, data, or quotations. If something is uncertain,
say so plainly using hedged language ("evidence suggests", "one view
holds that") rather than inventing supporting detail.
"""


# ──────────────────────────────────────────────────────────────────────────────
# Prompt builder
# ──────────────────────────────────────────────────────────────────────────────

def build_prompt(bundle: dict) -> str:
    lines = [
        r"% ── Assignment context (do not include this comment in output) ──",
        f"% Course       : {bundle.get('course_name', '')} ({bundle.get('course_code', '')})",
        f"% Assignment    : {bundle.get('assignment_name', '')}",
        f"% Due           : {bundle.get('due_date') or 'Not specified'}",
        f"% Max score     : {bundle.get('max_score') or 'Not specified'}",
        "",
        "ASSIGNMENT INSTRUCTIONS",
        "───────────────────────",
        bundle.get("instructions") or "(No written instructions found.)",
    ]

    # Attached instructor files (PDFs extracted to text)
    for att in bundle.get("attachments", []):
        if att.get("text"):
            lines += [
                "",
                f"ATTACHED DOCUMENT: {att['name']}",
                "─" * 40,
                att["text"],
            ]

    # Content documents found from the course content tab
    for doc in bundle.get("content_docs", []):
        if doc.get("text"):
            lines += [
                "",
                f"COURSE CONTENT DOCUMENT: {doc['name']}",
                "─" * 40,
                doc["text"],
            ]

    lines += [
        "",
        "─" * 60,
        "Write a complete, detailed, submission-ready answer for this assignment.",
        "Output valid LaTeX body content only. No preamble. No \\begin{document}.",
    ]

    return "\n".join(lines)


# ──────────────────────────────────────────────────────────────────────────────
# Provider dispatch
# ──────────────────────────────────────────────────────────────────────────────

def complete(bundle: dict) -> str:
    """
    Send the assignment bundle to the configured LLM.
    Returns a LaTeX body string (no preamble).
    """
    prompt = build_prompt(bundle)

    if PROVIDER == "openai":
        return _openai(prompt)
    elif PROVIDER == "anthropic":
        return _anthropic(prompt)
    elif PROVIDER == "google":
        return _google(prompt)
    else:
        raise ValueError(f"Unknown LLM_PROVIDER: {PROVIDER!r}")


def _openai(user_prompt: str) -> str:
    from openai import OpenAI
    client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
    response = client.chat.completions.create(
        model=OPENAI_MODEL,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user",   "content": user_prompt},
        ],
        temperature=0.4,
        max_tokens=8000,
    )
    return response.choices[0].message.content


def _anthropic(user_prompt: str) -> str:
    import anthropic
    client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))
    msg = client.messages.create(
        model=ANTHROPIC_MODEL,
        max_tokens=8000,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": user_prompt}],
    )
    return msg.content[0].text


def _google(user_prompt: str) -> str:
    import google.generativeai as genai
    genai.configure(api_key=os.getenv("GOOGLE_API_KEY"))
    model = genai.GenerativeModel(
        model_name=GOOGLE_MODEL,
        system_instruction=SYSTEM_PROMPT,
    )
    return model.generate_content(user_prompt).text
