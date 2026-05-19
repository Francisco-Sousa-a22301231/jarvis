"""Planner tests. Mocks the Haiku call."""
from __future__ import annotations

from unittest.mock import patch

from jarvis.agents import planner


def _haiku(value: str):
    return patch.object(planner, "haiku", return_value=value)


def test_clarify_when_haiku_says_yes():
    with _haiku('{"clarify": true, "question": "Which page"}'):
        q = planner.clarification("fix the bug")
    assert q == "Which page?"


def test_no_clarify_when_specific():
    with _haiku('{"clarify": false, "question": ""}'):
        q = planner.clarification("add dark mode toggle to /settings page")
    assert q is None


def test_empty_task_returns_none():
    q = planner.clarification("")
    assert q is None


def test_haiku_failure_returns_none():
    with patch.object(planner, "haiku", side_effect=RuntimeError("offline")):
        q = planner.clarification("anything")
    assert q is None


def test_garbage_response_returns_none():
    with _haiku("not even json"):
        q = planner.clarification("anything")
    assert q is None


def test_merge_clarification_includes_both():
    refined = planner.merge_clarification("fix bug", "Which page?", "the login screen")
    assert "fix bug" in refined
    assert "the login screen" in refined
    assert "Which page" in refined


def test_merge_empty_answer_returns_original():
    original = "fix bug"
    refined = planner.merge_clarification(original, "Which page?", "   ")
    assert refined == original
