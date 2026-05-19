"""Keyword fast-path for the router.

For unambiguous voice commands we skip the Haiku call entirely. Each spawn
of `claude -p` adds ~1-2s of latency; pattern-matching common phrases
locally reclaims that time at no quality cost (the patterns are explicit
about which utterances they match).

Order matters — the first matching pattern wins. Put more specific patterns
above broader ones.
"""
from __future__ import annotations

import re
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .router import Routed


# Each entry: (compiled_regex, skill_id, task_template_or_None)
# If task_template is None, we use the raw transcript as the task.
_PATTERNS: list[tuple[re.Pattern[str], str, str | None]] = [
    # Brief — daily summary
    (
        re.compile(r"\b(morning |evening )?brief( me)?\b|\bcatch me up\b", re.I),
        "brief",
        "Compose today's brief",
    ),
    # QA — run tests
    (
        re.compile(
            r"\b(run )?qa\b|\btest (what i just|the feature|that)\b|\bverify (the )?(feature|build)\b",
            re.I,
        ),
        "qa",
        "Run QA on the pending spec",
    ),
    # Trello — create (before query, since 'add a trello card' would also match query patterns)
    (
        re.compile(
            r"\b(add|create|make) (a )?(new )?(trello )?card\b|\bput (.+) on trello\b|\bremind me to\b",
            re.I,
        ),
        "trello_create",
        None,  # raw transcript carries the card content
    ),
    # Trello — query
    (
        re.compile(
            r"\b(show|what'?s? in|list|read) (my )?(doing|todo|backlog|in[- ]review|done) (list|cards?)\b|\bwhat'?s? on trello\b",
            re.I,
        ),
        "trello_query",
        None,
    ),
    # Calendar
    (
        re.compile(
            r"\b(what'?s? on (my )?(calendar|schedule|plate)|next meeting|today'?s? schedule)\b|\bcalendar today\b",
            re.I,
        ),
        "calendar",
        "Show today's calendar",
    ),
    # Mail
    (
        re.compile(
            r"\b(any |new |unread |check my )?(emails?|mail|inbox)\b",
            re.I,
        ),
        "mail",
        "Show unread mail",
    ),
    # Smalltalk / status
    (
        re.compile(
            r"^(hi|hello|hey|good (morning|evening|afternoon)|are you (there|online|alive))\b",
            re.I,
        ),
        "direct",
        None,
    ),
]


def try_fastpath(transcript: str) -> "Routed | None":
    """Return a Routed if the transcript matches a known pattern, else None."""
    from .router import Routed  # late import — avoids router<->fastpath cycle

    text = transcript.strip()
    if not text:
        return None
    for pattern, skill, template in _PATTERNS:
        if pattern.search(text):
            return Routed(skill=skill, task=template or text)
    return None
