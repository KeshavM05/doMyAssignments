"""
main.py — doMyAssignments FastAPI backend

Endpoints:
  POST /api/upload              — upload files, returns job_id
  POST /api/generate/{job_id}   — start generation, stream LaTeX via SSE
  GET  /api/jobs                — list all jobs
  GET  /api/jobs/{job_id}       — get single job status
  GET  /api/output/{job_id}     — download the .tex file
"""

import os
import uuid
import asyncio
from datetime import datetime
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, File, UploadFile, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse, FileResponse
from pydantic import BaseModel
from dotenv import load_dotenv

load_dotenv(dotenv_path=Path(__file__).parent.parent / ".env")
load_dotenv(dotenv_path=Path(__file__).parent / ".env")

from generate import build_content_blocks, stream_bedrock_vision

# ── App setup ──────────────────────────────────────────────────────────────

app = FastAPI(title="doMyAssignments API", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── Directories ────────────────────────────────────────────────────────────

ROOT       = Path(__file__).parent.parent
UPLOADS_DIR = Path(__file__).parent / "uploads"
OUTPUTS_DIR = ROOT / "outputs"

UPLOADS_DIR.mkdir(exist_ok=True)
OUTPUTS_DIR.mkdir(exist_ok=True)

# ── In-memory job store ────────────────────────────────────────────────────

jobs: dict[str, dict] = {}

ALLOWED_EXTENSIONS = {".pdf", ".docx", ".txt", ".md"}


class TextInput(BaseModel):
    text: str
    filename: str = "pasted_assignment.txt"


# ── Helpers ────────────────────────────────────────────────────────────────

def get_job_or_404(job_id: str) -> dict:
    if job_id not in jobs:
        raise HTTPException(status_code=404, detail=f"Job {job_id} not found")
    return jobs[job_id]


def job_summary(job: dict) -> dict:
    return {
        "id":           job["id"],
        "files":        job["files"],
        "status":       job["status"],
        "created_at":   job["created_at"],
        "output_path":  str(job["output_path"]) if job.get("output_path") else None,
        "error":        job.get("error"),
    }


# ── Routes ─────────────────────────────────────────────────────────────────

@app.get("/api/health")
def health():
    return {"status": "ok"}


@app.post("/api/upload")
async def upload_files(files: list[UploadFile] = File(...)):
    """
    Accept one or more files (PDF, DOCX, TXT), save to backend/uploads/,
    create a job record, and return the job_id.
    """
    if not files:
        raise HTTPException(status_code=400, detail="No files provided")

    job_id = str(uuid.uuid4())
    job_upload_dir = UPLOADS_DIR / job_id
    job_upload_dir.mkdir(parents=True, exist_ok=True)

    saved_files = []
    for upload in files:
        filename = upload.filename or "unnamed"
        ext = Path(filename).suffix.lower()
        if ext not in ALLOWED_EXTENSIONS:
            raise HTTPException(
                status_code=400,
                detail=f"Unsupported file type: {ext}. Allowed: {', '.join(ALLOWED_EXTENSIONS)}"
            )
        dest = job_upload_dir / filename
        content = await upload.read()
        dest.write_bytes(content)
        saved_files.append(filename)

    jobs[job_id] = {
        "id":          job_id,
        "files":       saved_files,
        "status":      "pending",
        "created_at":  datetime.utcnow().isoformat(),
        "output_path": None,
        "error":       None,
        "_upload_dir": str(job_upload_dir),
    }

    return {"job_id": job_id, "files": saved_files, "status": "pending"}


@app.post("/api/upload-text")
async def upload_text(body: TextInput):
    """
    Accept pasted plain text, save it as a .txt file,
    create a job record, and return the job_id.
    """
    if not body.text.strip():
        raise HTTPException(status_code=400, detail="Text content is empty")

    job_id = str(uuid.uuid4())
    job_upload_dir = UPLOADS_DIR / job_id
    job_upload_dir.mkdir(parents=True, exist_ok=True)

    filename = body.filename if body.filename.endswith(".txt") else body.filename + ".txt"
    dest = job_upload_dir / filename
    dest.write_text(body.text, encoding="utf-8")

    jobs[job_id] = {
        "id":          job_id,
        "files":       [filename],
        "status":      "pending",
        "created_at":  datetime.utcnow().isoformat(),
        "output_path": None,
        "error":       None,
        "_upload_dir": str(job_upload_dir),
    }

    return {"job_id": job_id, "files": [filename], "status": "pending"}


@app.post("/api/generate/{job_id}")
async def generate(job_id: str):
    """
    Start processing a job. Streams the LaTeX output back as SSE.
    Each event: data: <chunk>\\n\\n
    When done:  data: [DONE]\\n\\n
    """
    job = get_job_or_404(job_id)

    if job["status"] == "processing":
        raise HTTPException(status_code=409, detail="Job is already being processed")
    if job["status"] == "done":
        raise HTTPException(status_code=409, detail="Job already completed")

    job["status"] = "processing"
    job["error"] = None

    async def event_stream():
        try:
            upload_dir = Path(job["_upload_dir"])

            # Build content blocks for all uploaded files
            all_image_blocks = []
            all_text_parts = []

            for filename in job["files"]:
                filepath = str(upload_dir / filename)
                img_blocks, text = build_content_blocks(filepath)
                all_image_blocks.extend(img_blocks)
                if text:
                    all_text_parts.append(f"=== {filename} ===\n{text}")

            combined_text = "\n\n".join(all_text_parts)

            # Stream from Bedrock in a thread (boto3 is sync)
            loop = asyncio.get_event_loop()
            queue: asyncio.Queue = asyncio.Queue()

            def run_stream():
                try:
                    for chunk in stream_bedrock_vision(all_image_blocks, combined_text):
                        loop.call_soon_threadsafe(queue.put_nowait, chunk)
                    loop.call_soon_threadsafe(queue.put_nowait, None)  # sentinel
                except Exception as exc:
                    loop.call_soon_threadsafe(queue.put_nowait, exc)

            import threading
            thread = threading.Thread(target=run_stream, daemon=True)
            thread.start()

            full_output = []

            while True:
                item = await queue.get()
                if item is None:
                    # Done
                    break
                if isinstance(item, Exception):
                    raise item
                full_output.append(item)
                # SSE: escape newlines within a data field by splitting on newlines
                # Each line of a chunk must be prefixed with "data: "
                for line in item.split("\n"):
                    yield f"data: {line}\n"
                yield "\n"
                await asyncio.sleep(0)  # yield control

            # Save output
            latex_content = "".join(full_output)
            timestamp = datetime.utcnow().strftime("%Y-%m-%d_%H-%M")
            stem = Path(job["files"][0]).stem
            out_filename = f"{timestamp}_{stem}.tex"
            out_path = OUTPUTS_DIR / out_filename
            out_path.write_text(latex_content, encoding="utf-8")

            job["status"] = "done"
            job["output_path"] = str(out_path)

            yield "data: [DONE]\n\n"

        except Exception as exc:
            job["status"] = "error"
            job["error"] = str(exc)
            yield f"data: [ERROR] {str(exc)}\n\n"

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


@app.get("/api/jobs")
def list_jobs():
    """Return all jobs, newest first."""
    sorted_jobs = sorted(jobs.values(), key=lambda j: j["created_at"], reverse=True)
    return [job_summary(j) for j in sorted_jobs]


@app.get("/api/jobs/{job_id}")
def get_job(job_id: str):
    """Return a single job's status and metadata."""
    job = get_job_or_404(job_id)
    return job_summary(job)


@app.get("/api/output/{job_id}")
def download_output(job_id: str):
    """Download the generated .tex file for a completed job."""
    job = get_job_or_404(job_id)
    if job["status"] != "done" or not job.get("output_path"):
        raise HTTPException(status_code=404, detail="Output not ready yet")
    out_path = Path(job["output_path"])
    if not out_path.exists():
        raise HTTPException(status_code=404, detail="Output file not found on disk")
    return FileResponse(
        path=str(out_path),
        filename=out_path.name,
        media_type="text/plain",
    )
