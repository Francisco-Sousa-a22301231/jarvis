"""Memory module tests. Uses tmp_path so nothing touches ~/.jarvis."""
from __future__ import annotations

import pytest

from jarvis.memory import Memory, needs_history


@pytest.mark.parametrize(
    "transcript",
    [
        "do the same for the dashboard",
        "again, but for staging",
        "fix it",
        "test that",
        "those cards",
    ],
)
def test_needs_history_positives(transcript: str):
    assert needs_history(transcript)


@pytest.mark.parametrize(
    "transcript",
    [
        "add a dark mode toggle to settings",
        "what's on my calendar",
        "morning brief",
        "hello there",
    ],
)
def test_needs_history_negatives(transcript: str):
    assert not needs_history(transcript)


def test_memory_append_and_recent(tmp_path):
    m = Memory(path=tmp_path / "recent.md", max_entries=3)
    m.append("hello", "direct", "Hi there.")
    m.append("brief me", "brief", "3 meetings, 5 unread.")
    snippet = m.recent_snippet(n=2)
    assert "You: hello" in snippet
    assert "You: brief me" in snippet


def test_memory_trims_old_entries(tmp_path):
    m = Memory(path=tmp_path / "recent.md", max_entries=2)
    m.append("one", "direct", "a")
    m.append("two", "direct", "b")
    m.append("three", "direct", "c")
    snippet = m.recent_snippet(n=10)
    assert "one" not in snippet
    assert "two" in snippet
    assert "three" in snippet


def test_memory_clears_long_result(tmp_path):
    m = Memory(path=tmp_path / "recent.md")
    m.append("x", "direct", "a" * 1000)
    snippet = m.recent_snippet(n=1)
    # Stored result should be clipped to ~200 chars + ellipsis
    assert len(snippet) < 300
    assert "..." in snippet
