# ONQ Autopilot — Vision

## What This Is

ONQ Autopilot is a personal automation tool that watches your Queen's University
course portal (OnQ), detects new assignments as they are posted, gathers all
available information about each one, passes that context to a large language
model, and saves the completed answer as a polished PDF on your laptop.

It is not a submission bot. It does not touch the submission form. It produces
a document that you can read, verify, edit, and submit yourself.

## Why It Exists

University assignment workflows are repetitive in their overhead: log into the
portal, find the assignment, download the brief, locate related course notes,
open a document, start writing. The intellectual work is the hard part and the
part that should get your attention. Everything before it is friction.

This tool removes the friction layer. When a new assignment appears, the system
has already read the brief, pulled relevant course material, and drafted a
structured, well-written starting point by the time you sit down.

## Design Philosophy

**Local first.** Nothing submits anything. All outputs land on your machine.
You are always the final reviewer before anything goes anywhere.

**Human-sounding output.** The LLM is constrained by a strict set of banned
phrases and stylistic rules. The goal is prose that reads like a capable student
wrote it after thinking about the problem, not a paragraph that triggers every
AI-detector heuristic by the second sentence.

**Minimal configuration.** One `.env` file, one command. The tool figures out
your courses, finds the assignments, and gets to work.

**Extensible toward hosting.** The scraper and pipeline are written as clean
Python modules with no global state. The path from "CLI script on your laptop"
to "FastAPI service with a React dashboard on EC2" is a matter of adding an API
layer, not rewriting the core logic.

## What Good Looks Like

You open your laptop in the morning. You have three assignments due this week.
The `outputs/` folder already contains three PDFs — one per assignment — each a
detailed, properly formatted academic document. You read them, adjust the
wording in a few places, and submit. The whole review takes twenty minutes
instead of the three hours the raw writing would have taken.

That is the target state.

## Scope Boundaries

This tool is for **your personal use**. It reads your courses, runs on your
machine or a private server, and outputs files only you see. It is not a
service, not a product, and not designed to handle multiple users without
further work.

The submission question is deliberately left open. Auto-submission could be
added later behind an explicit flag after thorough testing. For now, the answer
is: the tool stops at the PDF.
