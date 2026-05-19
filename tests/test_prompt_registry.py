"""Prompt registry tests."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from jarvis.prompt_registry import PromptRegistry, PromptTemplate


def _registry(tmp_path: Path) -> PromptRegistry:
    return PromptRegistry(path=tmp_path / "prompts.json", epsilon=0.0)


def test_seeds_default_coder_template(tmp_path: Path):
    r = _registry(tmp_path)
    templates = r.templates_for("code")
    assert templates, "Expected default coder template to be seeded"
    assert templates[0].id == "coder_v1"
    assert "{task}" in templates[0].template


def test_render_substitutes_task(tmp_path: Path):
    r = _registry(tmp_path)
    tid, rendered = r.render("code", "add dark mode")
    assert tid == "coder_v1"
    assert "add dark mode" in rendered


def test_render_no_template_falls_back(tmp_path: Path):
    r = _registry(tmp_path)
    tid, rendered = r.render("nonexistent_skill", "do something")
    assert tid is None
    assert rendered == "do something"


def test_record_outcome_and_stats(tmp_path: Path):
    r = _registry(tmp_path)
    r.record_outcome("coder_v1", "task1", "success", "")
    r.record_outcome("coder_v1", "task2", "failure", "")
    r.record_outcome("coder_v1", "task3", "success", "")
    rows = {s.template_id: s for s in r.stats()}
    s = rows["coder_v1"]
    assert s.trials == 3
    assert s.successes == 2
    assert s.failures == 1
    assert s.win_rate == pytest.approx(2 / 3)


def test_ab_pick_with_epsilon_zero_prefers_higher_winrate(tmp_path: Path):
    r = PromptRegistry(path=tmp_path / "prompts.json", epsilon=0.0)
    # Add a second template + score them differently.
    r.add(PromptTemplate(id="coder_v2", skill="code", template="Better: {task}"))
    # Give v1 lots of wins, v2 more failures
    for _ in range(8):
        r.record_outcome("coder_v1", "x", "success")
    for _ in range(5):
        r.record_outcome("coder_v2", "x", "failure")
    for _ in range(2):
        r.record_outcome("coder_v2", "x", "success")
    # Epsilon=0 → deterministic greedy. Should always pick v1.
    for _ in range(10):
        picked = r.pick("code")
        assert picked is not None
        assert picked.id == "coder_v1"


def test_under_sampled_template_gets_priority(tmp_path: Path):
    r = PromptRegistry(path=tmp_path / "prompts.json", epsilon=0.0)
    # v1 has lots of stats. New v2 has none — should be explored.
    for _ in range(10):
        r.record_outcome("coder_v1", "x", "success")
    r.add(PromptTemplate(id="coder_v2", skill="code", template="New: {task}"))
    picks = {r.pick("code").id for _ in range(20)}
    assert "coder_v2" in picks


def test_set_active_toggles(tmp_path: Path):
    r = PromptRegistry(path=tmp_path / "prompts.json", epsilon=0.0)
    r.add(PromptTemplate(id="coder_v2", skill="code", template="x {task}"))
    assert r.set_active("coder_v2", False)
    active = r.templates_for("code", active_only=True)
    assert all(t.id != "coder_v2" for t in active)
    # And the picker won't pick it
    for _ in range(5):
        assert r.pick("code").id == "coder_v1"


def test_failures_for_returns_only_failures(tmp_path: Path):
    r = _registry(tmp_path)
    r.record_outcome("coder_v1", "ok task", "success")
    r.record_outcome("coder_v1", "bad task", "failure", "broke X")
    r.record_outcome("coder_v1", "meh task", "unknown")
    fails = r.failures_for("coder_v1")
    assert len(fails) == 1
    assert fails[0].task == "bad task"


def test_persistence_across_instances(tmp_path: Path):
    path = tmp_path / "prompts.json"
    r1 = PromptRegistry(path=path)
    r1.record_outcome("coder_v1", "x", "success")
    # New registry pointed at same file should see the record.
    r2 = PromptRegistry(path=path)
    rows = list(r2.stats())
    assert any(s.template_id == "coder_v1" and s.successes == 1 for s in rows)


def test_outcome_log_capped(tmp_path: Path):
    r = _registry(tmp_path)
    for i in range(2100):
        r.record_outcome("coder_v1", f"t{i}", "success")
    data = json.loads(r.path.read_text(encoding="utf-8"))
    assert len(data["results"]) <= 2000
