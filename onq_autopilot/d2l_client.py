"""
onq_autopilot/d2l_client.py
────────────────────────────
Thin wrapper around the D2L Valence REST API.

API version used: 1.82 (LMS v20.25.1+)
Reference: https://docs.valence.desire2learn.com/res/dropbox.html

All methods return parsed Python dicts/lists. Caller should handle errors.
"""

import os
import requests
from .auth import get_valid_tokens

BASE_URL    = os.getenv("ONQ_BASE_URL", "https://onq.queensu.ca")
API_VERSION = "1.82"


def _headers() -> dict:
    tokens = get_valid_tokens()
    return {"Authorization": f"Bearer {tokens['access_token']}"}


def _get(path: str, **kwargs) -> dict | list:
    url = f"{BASE_URL}/d2l/api/{path}"
    resp = requests.get(url, headers=_headers(), **kwargs)
    resp.raise_for_status()
    return resp.json()


def _post(path: str, **kwargs) -> dict | list:
    url = f"{BASE_URL}/d2l/api/{path}"
    resp = requests.post(url, headers=_headers(), **kwargs)
    resp.raise_for_status()
    return resp.json()


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

    Schema per item:
      OrgUnit.{Id, Name, Type, Code}
      Access.{IsActive, StartDate, EndDate, CanAccess}
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

    Each folder contains:
      Id, Name, CustomInstructions (HTML), DueDate, Attachments[],
      SubmissionType, Assessment.ScoreDenominator, ...
    """
    return _get(f"le/{API_VERSION}/{org_unit_id}/dropbox/folders/")


def get_dropbox_folder(org_unit_id: int, folder_id: int) -> dict:
    """Returns metadata for a single dropbox folder."""
    return _get(f"le/{API_VERSION}/{org_unit_id}/dropbox/folders/{folder_id}")


def get_my_submissions(org_unit_id: int, folder_id: int) -> list[dict]:
    """Returns the current user's submissions to a specific dropbox folder."""
    return _get(
        f"le/{API_VERSION}/{org_unit_id}/dropbox/folders/{folder_id}/submissions/mysubmissions/"
    )


def download_folder_attachment(
    org_unit_id: int, folder_id: int, file_id: int, save_path: str
):
    """
    Downloads a *folder-level* file attachment (i.e., the assignment brief PDF).
    These are files attached by the instructor to the dropbox folder itself.
    """
    url = (
        f"{BASE_URL}/d2l/api/le/{API_VERSION}"
        f"/{org_unit_id}/dropbox/folders/{folder_id}/attachments/{file_id}"
    )
    resp = requests.get(url, headers=_headers(), stream=True)
    resp.raise_for_status()
    os.makedirs(os.path.dirname(save_path), exist_ok=True)
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
    Submits a text-type response to a dropbox folder.
    Only works if the folder's SubmissionType is Text (1) or File or Text (4).

    NOTE: AUTO_SUBMIT must be explicitly enabled in .env.
    """
    if os.getenv("AUTO_SUBMIT", "false").lower() != "true":
        raise PermissionError(
            "AUTO_SUBMIT is disabled. Review the LLM output and set "
            "AUTO_SUBMIT=true in .env to enable automatic submission."
        )
    payload = {
        "TextSubmission": {"Html": text_html, "Text": ""},
        "Comment":        {"Html": comment, "Text": comment},
    }
    return _post(
        f"le/{API_VERSION}/{org_unit_id}/dropbox/folders/{folder_id}/submissions/",
        json=payload,
    )
