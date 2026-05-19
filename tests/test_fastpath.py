"""Fast-path router tests. No mocking needed — pure pattern matching."""
from __future__ import annotations

import pytest

from jarvis.fastpath import try_fastpath


@pytest.mark.parametrize(
    "transcript, expected_skill",
    [
        ("morning brief", "brief"),
        ("brief me", "brief"),
        ("catch me up", "brief"),
        ("run QA", "qa"),
        ("test what I just built", "qa"),
        ("verify the feature", "qa"),
        ("add a card to call Pedro", "trello_create"),
        ("create a new trello card", "trello_create"),
        ("remind me to fix the bug", "trello_create"),
        ("show my doing list", "trello_query"),
        ("what's in my todo cards", "trello_query"),
        ("what's on my calendar", "calendar"),
        ("next meeting", "calendar"),
        ("any new emails", "mail"),
        ("check my inbox", "mail"),
        ("hello", "direct"),
        ("good morning", "direct"),
        ("are you there", "direct"),
    ],
)
def test_fastpath_matches(transcript: str, expected_skill: str):
    result = try_fastpath(transcript)
    assert result is not None, f"Expected fast-path match for {transcript!r}"
    assert result.skill == expected_skill


@pytest.mark.parametrize(
    "transcript",
    [
        "refactor the auth module to use JWT tokens",  # code — no fast-path
        "explain the difference between TCP and UDP",  # direct, but not a greeting
        "",
        "   ",
    ],
)
def test_fastpath_misses(transcript: str):
    assert try_fastpath(transcript) is None


def test_fastpath_preserves_raw_transcript_when_no_template():
    """trello_create has template=None, so the full utterance becomes the task."""
    result = try_fastpath("remind me to deploy on Friday")
    assert result is not None
    assert result.skill == "trello_create"
    assert "deploy" in result.task.lower()
