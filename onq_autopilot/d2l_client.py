"""
onq_autopilot/d2l_client.py
────────────────────────────
Thin wrapper around the D2L Valence REST API.

Authentication: browser session cookies via session.get_requests_session()
API version:    1.82  (LMS v20.25.1+)
Reference:      https://docs.valence.desire2learn.com/res/dropbox.html

No OAuth tokens needed — we piggyback on the real browser session.
"""

import os
from pathlib import Path
from .session import get_requests_session

BASE_URL    = os.getenv("ONQ_BASE_URL", "https://onq.queensu.ca")
API_VERSION = "1.82"


def _get(path: str, **kwargs):
    s = get_requests_session()
    url = f"{BASE_URL}/d2l/api/{path}"
    resp = s.get(url, **kwargs)
    resp.raise_for_status()
    return resp.json()


def _post(path: str, **kwargs):
    s = get_requests_session()
    url = f"{BASE_URL}/d2l/api/{path}"
    # D2L requires the CSRF token for state-mutating calls
    csrf = _get_csrf_token(s)
    s.headers["X-Csrf-Token"] = csrf
    resp = s.post(url, **kwargs)
    resp.raise_for_status()
    return resp.json()


def _get_csrf_token(session) -> str:
    """
    D2L embeds a CSRF token in the page that is required for POST calls.
    We retrieve it from the /d2l/lp/auth/xsrf-tokens endpoint.
    """
    resp = session.get(f"{BASE_URL}/d2l/lp/auth/xsrf-tokens", timeout=10)
    if resp.status_code == 200:
        try:
            return resp.json().get("ReferrerToken", "")
        except Exception:
            pass
    return ""


# ──────────────────────────────────────────────────────────────────────────────
# Enrollment / Courses
# ──────────────────────────────────────────────────────────────────────────────

def get_my_user_id() -> int:
    """Returns the authenticated user's D2L user ID."""
    data = _get(f"lp/{API_VERSION}/users/whoami")
    return data["Identifier"]


def get_my_enrollments() -> list[dict]:
    """
    Returns all org units (courses) the current user is enrolled in.
    """
    data = _get(f"lp/{API_VERSION}/enrollments/myenrollments/")
    return data.get("Items", [])


def get_active_courses() -> list[dict]:
    """Filters enrollments to only active, accessible courses."""
    return [
        e for e in get_my_enrollments()
        if e.get("Access", {}).get("IsActive")
        and e.get("Access", {}).get("CanAccess")
    ]


# ──────────────────────────────────────────────────────────────────────────────
# Dropbox / Assignments
# ──────────────────────────────────────────────────────────────────────────────

def get_dropbox_folders(org_unit_id: int) -> list[dict]:
    """
    Returns all assignment (dropbox) folders for a given course.
    """
    return _get(f"le/{API_VERSION}/{org_unit_id}/dropbox/folders/")


def get_dropbox_folder(org_unit_id: int, folder_id: int) -> dict:
    """Returns metadata for a single dropbox folder."""
    return _get(f"le/{API_VERSION}/{org_unit_id}/dropbox/folders/{folder_id}")


def get_my_submissions(org_unit_id: int, folder_id: int) -> list[dict]:
    """Returns the current user's submissions to a specific dropbox folder."""
    return _get(
        f"le/{API_VERSION}/{org_unit_id}/dropbox/folders/{folder_id}"
        f"/submissions/mysubmissions/"
    )


def download_folder_attachment(
    org_unit_id: int,
    folder_id: int,
    file_id: int,
    save_path: str,
) -> str:
    """
    Downloads a folder-level file attachment (assignment brief / rubric PDF).
    Returns the local save path.
    """
    s = get_requests_session()
    url = (
        f"{BASE_URL}/d2l/api/le/{API_VERSION}"
        f"/{org_unit_id}/dropbox/folders/{folder_id}/attachments/{file_id}"
    )
    resp = s.get(url, stream=True, timeout=60)
    resp.raise_for_status()

    Path(save_path).parent.mkdir(parents=True, exist_ok=True)
    with open(save_path, "wb") as f:
        for chunk in resp.iter_content(chunk_size=8192):
            f.write(chunk)
    return save_path


def submit_text_submission(
    org_unit_id: int,
    folder_id: int,
    text_html: str,
    comment: str = "",
) -> dict:
    """
    Submits a text response to a dropbox folder.
    Only works if SubmissionType is Text (1) or File or Text (4).
    Guarded by AUTO_SUBMIT env var.
    """
    if os.getenv("AUTO_SUBMIT", "false").lower() != "true":
        raise PermissionError(
            "AUTO_SUBMIT is disabled. Review outputs and set "
            "AUTO_SUBMIT=true in .env to enable automatic submission."
        )
    payload = {
        "TextSubmission": {"Html": text_html, "Text": ""},
        "Comment":        {"Html": comment,   "Text": comment},
    }
    return _post(
        f"le/{API_VERSION}/{org_unit_id}/dropbox/folders/{folder_id}/submissions/",
        json=payload,
    )
