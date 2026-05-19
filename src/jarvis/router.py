"""Haiku-powered router: voice transcript -> (skill_id, cleaned task).

Low-context discipline: the router NEVER sees conversation history. It sees
only the static skill catalog and the latest transcript. Same input → same
decision, so the system block hits the prompt cache on every call after the
first.
"""
from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass

from .llm import haiku
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


def route(transcript: str) -> Routed:
    """Classify the transcript. Falls back to 'direct' on any parse failure."""
    valid = set(skill_ids())
    raw = haiku(
        system=_system_prompt(),
        user=transcript.strip(),
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
