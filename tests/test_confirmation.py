"""Confirmation gate tests."""
from __future__ import annotations

import pytest

from jarvis.confirmation import is_yes, proposal_for


@pytest.mark.parametrize(
    "transcript",
    [
        "yes",
        "yeah",
        "ok",
        "do it",
        "confirm",
        "go ahead",
        "yep please",
        "sure",
    ],
)
def test_is_yes_positive(transcript: str):
    assert is_yes(transcript)


@pytest.mark.parametrize(
    "transcript",
    [
        "no",
        "cancel",
        "stop",
        "never mind",
        "wait",
        "",
        "   ",
        "umm",
        "I think so",  # ambiguous → not a clear yes
    ],
)
def test_is_yes_negative(transcript: str):
    assert not is_yes(transcript)


def test_no_beats_yes_in_same_utterance():
    """If both yes and no patterns match, no wins. Reduces false positives."""
    assert not is_yes("yes, no actually cancel")


def test_proposal_includes_skill_and_task():
    p = proposal_for("trello_create", "call Pedro tomorrow")
    assert "Trello" in p
    assert "Pedro" in p


def test_proposal_fallback_for_unknown_skill():
    p = proposal_for("future_skill_xyz", "do stuff")
    assert "future_skill_xyz" in p
    assert "do stuff" in p
