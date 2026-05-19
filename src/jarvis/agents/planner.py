"""Planner: pre-coder clarification step for ambiguous tasks.

A vague task ("fix the auth bug") burns a full Claude Code spawn and usually
comes back with the wrong fix because Claude Code had to guess. One Haiku
call up front can ask the single most useful clarifying question and save
that round trip.

The planner is intentionally narrow: it asks AT MOST one question, and
only when the task is genuinely under-specified. Most code tasks pass
through unchanged.

Loop integration (in loop.py): if decision.skill == "code", call
planner.clarification(task). If it returns a string, speak it, record the
voice answer, append it to the task. Then dispatch as usual.
"""
from __future__ import annotations

import json
import logging
import re

from ..llm import haiku

log = logging.getLogger(__name__)


_SYSTEM = """You are deciding whether a developer's coding request is specific enough to start work, or whether ONE clarifying question would meaningfully change the implementation.

You will see the request. Reply with ONLY a JSON object on a single line:

{"clarify": true,  "question": "<one short question — 8 words or less>"}
or
{"clarify": false, "question": ""}

Rules:
- Default to NOT asking. Set clarify=false unless the missing info materially changes the code.
- If you ask, the question must have a quick verbal answer (one phrase). Don't ask compound questions.
- Don't ask about style, naming, or which file — those are not blockers.
- DO ask when the request specifies a behaviour but not a target (e.g. "fix the auth bug" — which bug? auth on web or mobile?).
"""

_JSON_RE = re.compile(r"\{.*\}", re.DOTALL)


def clarification(task: str) -> str | None:
    """Return a one-line clarifying question, or None if the task is fine.

    Failures (Haiku unreachable, parse errors) return None — the planner
    is a quality nudge, not a blocker.
    """
    if not task or not task.strip():
        return None
    try:
        raw = haiku(system=_SYSTEM, user=task.strip(), max_tokens=80, cache=True)
    except Exception:
        log.exception("Planner Haiku call failed")
        return None
    log.debug("Planner raw: %r", raw)

    match = _JSON_RE.search(raw)
    if not match:
        return None
    try:
        data = json.loads(match.group(0))
    except (json.JSONDecodeError, AttributeError):
        return None
    if not data.get("clarify"):
        return None
    q = str(data.get("question", "")).strip()
    if not q:
        return None
    if not q.endswith("?"):
        q += "?"
    return q


def merge_clarification(task: str, question: str, answer: str) -> str:
    """Build the refined task string sent to the coder.

    Phrasing keeps the original request first (the coder reads top-down).
    """
    answer = answer.strip()
    if not answer:
        return task
    return (
        f"{task.strip()}\n\n"
        f"Clarification — {question.strip()} {answer}"
    )
