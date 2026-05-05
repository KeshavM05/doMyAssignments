"""
onq_autopilot/llm.py
─────────────────────
Routes an AssignmentBundle to the configured LLM provider and returns
the completed answer as a string.

Supported providers (set LLM_PROVIDER in .env):
  - openai    (GPT-4o, etc.)
  - anthropic (Claude)
  - google    (Gemini)

The prompt template is deliberately thorough — it gives the LLM full
context, the grading weight, submission type constraints, and instructs
it to produce a submission-ready response only.
"""

import os
from dotenv import load_dotenv

load_dotenv()

PROVIDER       = os.getenv("LLM_PROVIDER", "openai").lower()
OPENAI_MODEL   = os.getenv("OPENAI_MODEL", "gpt-4o")
ANTHROPIC_MODEL = os.getenv("ANTHROPIC_MODEL", "claude-opus-4-5")
GOOGLE_MODEL   = os.getenv("GOOGLE_MODEL", "gemini-2.5-pro")


# ──────────────────────────────────────────────────────────────────────────────
# Prompt Builder
# ──────────────────────────────────────────────────────────────────────────────

SYSTEM_PROMPT = """\
You are an expert academic assistant helping a university student complete \
an assignment. Your goal is to produce a complete, accurate, and \
well-structured response that fully addresses the assignment requirements.

Rules:
1. Respond ONLY with the assignment answer — no preamble, no meta-commentary.
2. Match the academic level and discipline implied by the course and assignment.
3. Cite sources in APA format where appropriate.
4. If the submission type is "Text", format your answer in clean prose or \
   structured markdown (headings, bullets) as fits the question.
5. If the submission type is "File", produce content suitable for a Word doc \
   (the pipeline will wrap it into a .docx).
6. Do NOT hallucinate facts. If you are unsure, say so clearly within the answer.
"""


def build_prompt(bundle: dict) -> str:
    lines = [
        f"# Assignment: {bundle['assignment_name']}",
        f"**Course:** {bundle['course_name']} ({bundle['course_code']})",
        f"**Due:** {bundle.get('due_date') or 'Not specified'}",
        f"**Max score:** {bundle.get('max_score') or 'Not specified'}",
        f"**Submission type:** {bundle['submission_type']}",
        "",
        "## Instructions",
        bundle["instructions"] or "(No written instructions provided.)",
    ]

    for att in bundle.get("attachments", []):
        lines += [
            "",
            f"## Attached file: {att['name']}",
            att["text"],
        ]

    lines += [
        "",
        "---",
        "Produce a complete, submission-ready answer for this assignment.",
    ]
    return "\n".join(lines)


# ──────────────────────────────────────────────────────────────────────────────
# Provider dispatch
# ──────────────────────────────────────────────────────────────────────────────

def complete(bundle: dict) -> str:
    """
    Send the assignment bundle to the configured LLM and return the answer.
    """
    user_prompt = build_prompt(bundle)

    if PROVIDER == "openai":
        return _openai(user_prompt)
    elif PROVIDER == "anthropic":
        return _anthropic(user_prompt)
    elif PROVIDER == "google":
        return _google(user_prompt)
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
        temperature=0.3,
    )
    return response.choices[0].message.content


def _anthropic(user_prompt: str) -> str:
    import anthropic
    client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))
    message = client.messages.create(
        model=ANTHROPIC_MODEL,
        max_tokens=8096,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": user_prompt}],
    )
    return message.content[0].text


def _google(user_prompt: str) -> str:
    import google.generativeai as genai
    genai.configure(api_key=os.getenv("GOOGLE_API_KEY"))
    model = genai.GenerativeModel(
        model_name=GOOGLE_MODEL,
        system_instruction=SYSTEM_PROMPT,
    )
    response = model.generate_content(user_prompt)
    return response.text
