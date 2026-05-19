"""Prompt evolution tests. Mocks Haiku."""
from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from jarvis.prompt_evolution import evolve
from jarvis.prompt_registry import PromptRegistry, PromptTemplate


def _registry(tmp_path: Path) -> PromptRegistry:
    return PromptRegistry(path=tmp_path / "prompts.json", epsilon=0.0)


def test_evolve_skips_when_not_enough_failures(tmp_path: Path):
    r = _registry(tmp_path)
    # Default coder_v1 with zero failures
    result = evolve(r, skill="code")
    assert not result.success
    assert "failures" in result.message.lower()


def test_evolve_produces_new_template_from_failures(tmp_path: Path):
    r = _registry(tmp_path)
    for i in range(5):
        r.record_outcome("coder_v1", f"task {i}", "failure", "wrong file modified")

    haiku_response = (
        '{"template": "You are a coding agent. Be careful. Task: {task}", '
        '"rationale": "Emphasize precision"}'
    )
    with patch("jarvis.prompt_evolution.haiku", return_value=haiku_response):
        result = evolve(r, skill="code")
    assert result.success
    assert result.parent_id == "coder_v1"
    assert result.new_id and result.new_id.startswith("coder_v")
    # New template registered + active
    active_ids = {t.id for t in r.templates_for("code", active_only=True)}
    assert result.new_id in active_ids


def test_evolve_handles_garbage_response(tmp_path: Path):
    r = _registry(tmp_path)
    for _ in range(5):
        r.record_outcome("coder_v1", "x", "failure")
    with patch("jarvis.prompt_evolution.haiku", return_value="not json"):
        result = evolve(r, skill="code")
    assert not result.success


def test_evolve_picks_worst_when_multiple_active(tmp_path: Path):
    r = _registry(tmp_path)
    r.add(PromptTemplate(id="coder_v2", skill="code", template="Other: {task}"))
    # v1: 1 success / 4 failures = 20% win
    r.record_outcome("coder_v1", "t", "success")
    for _ in range(4):
        r.record_outcome("coder_v1", "t", "failure")
    # v2: 4 successes / 4 failures = 50% win
    for _ in range(4):
        r.record_outcome("coder_v2", "t", "success")
    for _ in range(4):
        r.record_outcome("coder_v2", "t", "failure")

    with patch("jarvis.prompt_evolution.haiku", return_value='{"template":"New: {task}"}'):
        result = evolve(r, skill="code")
    assert result.success
    assert result.parent_id == "coder_v1"  # the worse performer


def test_evolution_adds_task_placeholder_if_missing(tmp_path: Path):
    r = _registry(tmp_path)
    for _ in range(5):
        r.record_outcome("coder_v1", "x", "failure")
    # LLM forgot the placeholder
    with patch(
        "jarvis.prompt_evolution.haiku",
        return_value='{"template": "Just do it well."}',
    ):
        result = evolve(r, skill="code")
    assert result.success
    new = r.get(result.new_id)
    assert new is not None
    assert "{task}" in new.template
