"""Verify the canned-response shortcuts skip the LLM call.

Each shortcut saves a ~2 second `claude -p` spawn — the biggest single
latency win for smalltalk.
"""
from __future__ import annotations

import re

from unittest.mock import patch

from jarvis.agents import direct


def _no_haiku():
    """Context manager — fail loud if haiku gets called."""
    return patch.object(direct, "haiku", side_effect=AssertionError("LLM was called"))


def test_hello_is_canned():
    with _no_haiku():
        out = direct.DirectAgent().execute("hello")
    assert out and len(out) < 40


def test_good_morning_is_canned():
    with _no_haiku():
        out = direct.DirectAgent().execute("good morning")
    assert "morning" in out.lower()


def test_thanks_is_canned():
    with _no_haiku():
        out = direct.DirectAgent().execute("thanks")
    assert out


def test_are_you_there_is_canned():
    with _no_haiku():
        out = direct.DirectAgent().execute("are you there")
    assert out


def test_what_time_is_canned():
    with _no_haiku():
        out = direct.DirectAgent().execute("what time is it")
    # Should look like a time, e.g. "It's 9:46 AM."
    assert re.search(r"\d{1,2}:\d{2}\s*(AM|PM)", out, re.I)


def test_unknown_falls_through_to_haiku():
    with patch.object(direct, "haiku", return_value="A short answer.") as fake:
        out = direct.DirectAgent().execute("what's the capital of Portugal")
    fake.assert_called_once()
    assert out == "A short answer."
