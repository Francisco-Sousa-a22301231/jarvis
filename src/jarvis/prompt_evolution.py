"""Failure-driven prompt evolution.

Periodically (manually via `jarvis prompts evolve`), pick the worst-performing
active template that has enough samples, feed its recent failure cases to
Claude, and ask for an improved version. Add the new version as a sibling
template — don't deactivate the old one. The A/B selector will start sending
traffic to the new one; over time it'll win or lose on evidence.

Why manual: we want the human in the loop on prompt changes for now. Auto-
evolve every N failures is a future option once we trust the loop.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from uuid import uuid4

from .llm import haiku
from .prompt_registry import PromptRegistry, PromptTemplate

log = logging.getLogger(__name__)


MIN_FAILURES_TO_EVOLVE = 3
MAX_FAILURE_SAMPLES = 8


@dataclass
class EvolutionResult:
    parent_id: str | None
    new_id: str | None
    message: str

    @property
    def success(self) -> bool:
        return self.new_id is not None


_SYSTEM = """You are improving a prompt template for a coding agent.

You will see:
  - The current template (its text)
  - A handful of FAILED tasks that used this template — the user's words and a short detail of why the run was deemed a failure.

Reply with a JSON object on a single line, no markdown fences:

{"template": "<improved template text, including a {task} placeholder>", "rationale": "<one sentence on what you changed and why>"}

Constraints:
- Keep the {task} placeholder; the runtime substitutes the user's actual request there.
- The whole template should be under 600 characters.
- Do NOT explain to the model what 'success' looks like — just give better instructions for handling whatever request comes next.
- Don't promise behaviour the model can't deliver (no time-travel, no opening external tools).
"""


def evolve(
    registry: PromptRegistry,
    skill: str = "code",
) -> EvolutionResult:
    """Generate an improved sibling template for the worst-performing one."""
    stats = {s.template_id: s for s in registry.stats()}
    active = registry.templates_for(skill, active_only=True)

    # Find the worst with enough failure signal.
    candidates: list[tuple[float, PromptTemplate]] = []
    for tpl in active:
        s = stats.get(tpl.id)
        if not s or s.failures < MIN_FAILURES_TO_EVOLVE:
            continue
        candidates.append((s.win_rate, tpl))
    if not candidates:
        return EvolutionResult(
            None,
            None,
            f"No template for skill={skill!r} has at least "
            f"{MIN_FAILURES_TO_EVOLVE} failures yet — nothing to evolve.",
        )
    candidates.sort(key=lambda pair: pair[0])  # ascending: lowest win rate first
    parent = candidates[0][1]

    failures = registry.failures_for(parent.id, n=MAX_FAILURE_SAMPLES)
    if not failures:
        return EvolutionResult(
            parent.id, None,
            "Parent template has stats but no failure rows — inconsistent state.",
        )

    failure_block = "\n".join(
        f"- task: {f.task}\n  detail: {f.detail or '(no detail)'}" for f in failures
    )
    user = (
        f"Current template:\n---\n{parent.template}\n---\n\n"
        f"Failed tasks:\n{failure_block}"
    )

    try:
        raw = haiku(
            system=_SYSTEM,
            user=user,
            max_tokens=800,
            cache=False,  # input varies per evolution
        )
    except Exception as e:
        log.exception("Evolution Haiku call failed")
        return EvolutionResult(parent.id, None, f"Haiku call failed: {e}")

    new_template_text = _extract_template(raw)
    if not new_template_text:
        return EvolutionResult(
            parent.id, None, f"Couldn't parse Haiku output: {raw[:200]!r}",
        )
    if "{task}" not in new_template_text:
        new_template_text = new_template_text.rstrip() + "\n\nTask: {task}"

    new_id = f"{parent.id.split('_v')[0]}_v{_short_uuid()}"
    registry.add(
        PromptTemplate(
            id=new_id,
            skill=parent.skill,
            template=new_template_text,
            parent_id=parent.id,
            created_at=datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            active=True,
        )
    )
    return EvolutionResult(parent.id, new_id, f"Added {new_id} (from {parent.id}).")


def _extract_template(raw: str) -> str:
    import json
    import re

    match = re.search(r"\{.*\}", raw, re.DOTALL)
    if not match:
        return ""
    try:
        data = json.loads(match.group(0))
    except json.JSONDecodeError:
        return ""
    return str(data.get("template", "")).strip()


def _short_uuid() -> str:
    return uuid4().hex[:6]
