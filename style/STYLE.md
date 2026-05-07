# Keshav's Writing Style Guide

## Document Structure
- Cover page with: course name, assignment number, "Keshav Mehndiratta", Student ID: 20416565, \today
- Sections use `\section*{Problem N: Title}` — no numbering via LaTeX, manual problem labels
- Subsections use `\subsection*{(a) Title}`
- `\newpage` between major problems
- No table of contents

## LaTeX Preamble (always use this exact setup)
```latex
\documentclass[12pt]{article}
\usepackage{amsmath, amssymb, geometry, graphicx, float, booktabs, array}
\geometry{a4paper, margin=1in}
\setlength{\parindent}{0pt}
\setlength{\parskip}{0.75em}
```

## Writing Style
- **Concise but complete** — answer exactly what's asked, no padding
- **No fluff** — skip "In this problem we will..." just start solving
- State what you're doing, do it, explain the result
- Short declarative sentences for setup: "The derivative is..." / "We evaluate at..."
- Slightly longer sentences for analysis/insight but never rambling
- End sections with a clean one-liner conclusion when appropriate

## Hard Rules (never break these)
- NO semicolons (;)
- NO em dashes (—)
- NO ellipses (...)
- NO: "Furthermore", "Moreover", "Additionally", "In conclusion", "It is important to note"
- NO: "delve", "leverage", "robust", "comprehensive", "multifaceted", "utilize"
- NO filler openers like "In this section..." or "This problem asks us to..."

## Math Formatting
- Standalone equations: `\[ ... \]` or `equation` environment
- Inline math: `$...$`
- Multi-line derivations: `align*` environment
- Iteration results: `itemize` with `\textbf{Iteration k:}` labels
- Matrices: `pmatrix`

## Tables
- Always use `booktabs` style: `\toprule`, `\midrule`, `\bottomrule`
- `[H]` float specifier always
- Caption above the table
- Resize wide tables with `\resizebox{0.95\textwidth}{!}{...}`
- Side-by-side tables: `minipage` at `.45\textwidth` with `\hfill` between

## Numbers & Precision
- Show 4-6 decimal places for iterative methods
- Bold the final/optimal answer in tables
- Always verify numerical results analytically when possible

## Tone
- Confident and direct — "The algorithm converges in 4 iterations" not "It appears that..."
- Brief insight after results — one or two sentences explaining *why* something happened
- No hedging unless genuinely uncertain about something
