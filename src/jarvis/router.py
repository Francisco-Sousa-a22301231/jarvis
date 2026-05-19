"""Haiku-powered router: voice transcript -> (skill_id, cleaned task).

Low-context discipline: by default the router sees only the static skill
catalog and the latest transcript — same input → same decision → prompt-cache
hit on every call after the first.

History (last 2 utterances) is loaded *only* when the transcript looks
anaphoric (contains "it", "that", "same", "again", ...). For ~80% of
utterances we pay zero memory tokens; for the rest, history is ~80 extra
tokens for a much better resolution.
"""
from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass

from .fastpath import try_fastpath
from .llm import haiku
from .memory import Memory, needs_history
from .skills import catalog_lines, skill_ids

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class Routed:
    skill: str
    task: str


_ROUTER_SYSTEM = """You are a router for a voice assistant.

Map the user's voice utterance to exactly ONE skill ID and rewrite it as a clean task description.

Reply with ONLY a JSON object on one line, no prose, no markdown fences:
{{"skill": "<skill_id>", "task": "<rewritten task>"}}

Available skills:
{catalog}

Rules:
1. Pick exactly ONE skill.
2. If the request fits no skill clearly, use "direct".
3. Rewrite `task` as a clear, complete imperative sentence.
4. Never include explanations or markdown."""


_JSON_RE = re.compile(r"\{.*\}", re.DOTALL)


def _system_prompt() -> str:
    return _ROUTER_SYSTEM.format(catalog=catalog_lines())


def route(transcript: str, memory: Memory | None = None) -> Routed:
    """Classify the transcript. Tries the keyword fast-path first to skip
    a Haiku spawn on unambiguous phrases. Falls back to 'direct' on any
    parse failure.

    If `memory` is given AND the transcript looks anaphoric, the most recent
    2 entries are included as context for the Haiku router. Otherwise no
    history is loaded — keeps the cache hit and the per-call cost minimal.
    """
    fast = try_fastpath(transcript)
    if fast is not None:
        log.info("Fast-path: %s | %s", fast.skill, fast.task)
        return fast

    valid = set(skill_ids())
    user_block = transcript.strip()
    if memory is not None and needs_history(transcript):
        snippet = memory.recent_snippet(n=2)
        if snippet:
            user_block = (
                "Recent context:\n"
                f"{snippet}\n"
                "---\n"
                f"Current utterance: {transcript.strip()}"
            )
            log.info("Router using memory (%d chars)", len(snippet))

    raw = haiku(
        system=_system_prompt(),
        user=user_block,
        max_tokens=120,
        cache=True,
    )
    log.debug("router raw=%r", raw)

    match = _JSON_RE.search(raw)
    if not match:
        log.warning("Router returned non-JSON: %r — falling back to direct", raw)
        return Routed(skill="direct", task=transcript.strip())

    try:
        data = json.loads(match.group(0))
        skill = str(data.get("skill", "")).strip()
        task = str(data.get("task", "")).strip() or transcript.strip()
    except (json.JSONDecodeError, AttributeError) as e:
        log.warning("Router JSON parse failed (%s): %r", e, raw)
        return Routed(skill="direct", task=transcript.strip())

    if skill not in valid:
        log.warning("Router picked unknown skill %r; falling back to direct", skill)
        skill = "direct"
    return Routed(skill=skill, task=task)
