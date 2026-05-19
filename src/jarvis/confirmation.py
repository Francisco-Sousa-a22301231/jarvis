"""Voice confirmation gate for destructive / visible-to-others actions.

Phase 4 wires this into the loop for skills marked `requires_confirm`. The
flow is:

  1. Loop builds a short proposal sentence ("Add 'X' to Trello").
  2. mouth.speak(proposal + " Confirm?")
  3. ears.record_utterance() — short window, generous silence
  4. transcribe, then is_yes() → execute or speak "Cancelled."

If you add a skill that sends mail, pushes code, runs a payment, or otherwise
acts on the outside world, set requires_confirm=True in skills.py.
"""
from __future__ import annotations

import re

_YES_RE = re.compile(
    r"\b(yes|yeah|yep|yup|sure|ok|okay|go(?: ahead)?|do it|confirm(?:ed)?|"
    r"please|please do|right|correct|affirmative)\b",
    re.I,
)
_NO_RE = re.compile(
    r"\b(no|nope|nah|cancel|stop|abort|never mind|nevermind|wait)\b",
    re.I,
)


def is_yes(transcript: str) -> bool:
    """True only if the transcript clearly affirms. Silence / unclear → False."""
    if not transcript or not transcript.strip():
        return False
    if _NO_RE.search(transcript):
        return False
    return bool(_YES_RE.search(transcript))


def proposal_for(skill: str, task: str) -> str:
    """Build a short, speakable description of the proposed action.

    For skills with complex extraction (like mail_send, which needs to
    resolve a recipient, subject and body), the agent itself implements
    a `propose(task)` method and the loop prefers that. This function is
    the static fallback.
    """
    if skill == "trello_create":
        return f"I'll add to Trello: {task}."
    if skill == "mail_send":
        return f"I'll send the email: {task}."
    # Generic fallback — shouldn't happen if skills.py and this stay in sync.
    return f"I'll run {skill}: {task}."
