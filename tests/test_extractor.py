"""
tests/test_extractor.py
────────────────────────
Unit tests for the extractor module.
No network calls — all D2L responses are mocked.
"""

import pytest
from onq_autopilot.extractor import html_to_text, build_assignment_bundle


def test_html_to_text_basic():
    html = "<h1>Assignment 1</h1><p>Write a 500-word essay on <strong>climate</strong>.</p>"
    result = html_to_text(html)
    assert "Assignment 1" in result
    assert "climate" in result


def test_html_to_text_empty():
    assert html_to_text("") == ""
    assert html_to_text(None) == ""


def test_build_bundle_basic():
    course = {
        "OrgUnit": {"Id": 123, "Name": "CISC 101", "Code": "CISC101"}
    }
    folder = {
        "Id": 456,
        "Name": "Assignment 1",
        "DueDate": "2026-05-15T23:59:00Z",
        "CustomInstructions": {"Html": "<p>Write a report.</p>", "Text": ""},
        "SubmissionType": "1",
        "Assessment": {"ScoreDenominator": 100.0},
        "TotalUsersWithSubmissions": 0,
        "Attachments": [],
    }
    bundle = build_assignment_bundle(course, folder, [])

    assert bundle["course_name"] == "CISC 101"
    assert bundle["assignment_name"] == "Assignment 1"
    assert bundle["submission_type"] == "Text"
    assert bundle["max_score"] == 100.0
    assert "Write a report" in bundle["instructions"]
    assert bundle["already_submitted"] is False
    assert bundle["attachments"] == []


def test_build_bundle_no_instructions():
    course = {"OrgUnit": {"Id": 1, "Name": "TEST", "Code": "T101"}}
    folder = {
        "Id": 1,
        "Name": "HW1",
        "CustomInstructions": None,
        "SubmissionType": "0",
        "Assessment": None,
        "TotalUsersWithSubmissions": 1,
        "Attachments": [],
    }
    bundle = build_assignment_bundle(course, folder, [])
    assert bundle["instructions"] == ""
    assert bundle["already_submitted"] is True
