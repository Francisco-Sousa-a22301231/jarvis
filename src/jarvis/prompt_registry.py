"""Versioned prompt templates with A/B selection and outcome tracking.

Why this exists: a Claude Code "task" is more than the user's words — it's
the user's words wrapped in a preamble that tells Claude how to behave for
this codebase. That preamble matters and we don't know in advance what
phrasing works best. So we keep several versions, pick one per dispatch
(weighted by past success), and let evidence accumulate.

Storage: a single JSON file at ~/.jarvis/prompts.json. Two top-level keys:
  - templates: [{id, skill, template, parent_id, created_at, active}, ...]
  - results:   [{template_id, task, outcome, timestamp, detail}, ...]

Selection: epsilon-greedy.
  - With prob `epsilon` (default 0.15): pick an active template uniformly
    at random — keeps exploring even when one looks like a winner.
  - Otherwise: pick the one with the highest success rate among active
    templates with at least `min_samples` trials. Untried templates win
    ties so a freshly evolved template gets a shot.

The `record_outcome()` API is intentionally loose ("success" / "failure" /
"unknown"). The QA agent provides the strongest signal; the user can also
score manually via `jarvis prompts feedback`.
"""
from __future__ import annotations

import json
import logging
import random
import threading
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

log = logging.getLogger(__name__)

DEFAULT_PATH = Path.home() / ".jarvis" / "prompts.json"
DEFAULT_EPSILON = 0.15
MIN_SAMPLES_FOR_GREEDY = 5


@dataclass(frozen=True)
class PromptTemplate:
    id: str
    skill: str
    template: str  # may contain {task} placeholder
    parent_id: str | None = None
    created_at: str = ""
    active: bool = True

    def render(self, task: str) -> str:
        if "{task}" in self.template:
            return self.template.replace("{task}", task)
        # Backwards-compatible: append task if no placeholder.
        return f"{self.template}\n\nTask: {task}"


@dataclass
class Outcome:
    template_id: str
    task: str
    outcome: str  # "success" | "failure" | "unknown"
    timestamp: str
    detail: str = ""


@dataclass
class TemplateStats:
    template_id: str
    trials: int
    successes: int
    failures: int
    unknown: int

    @property
    def win_rate(self) -> float:
        scored = self.successes + self.failures
        return self.successes / scored if scored > 0 else 0.0


_DEFAULT_CODER_TEMPLATE = (
    "You are completing a coding task in this repository. Match existing code style "
    "(naming, layout, framework conventions). Prefer minimal, surgical changes over "
    "broad refactors. Don't introduce new dependencies unless the task clearly needs "
    "them. Add tests where they make sense for the change.\n\n"
    "Task: {task}"
)


class PromptRegistry:
    def __init__(self, path: Path | None = None, epsilon: float = DEFAULT_EPSILON):
        self.path = path or DEFAULT_PATH
        self.epsilon = epsilon
        self._lock = threading.Lock()
        self._data: dict | None = None
        self._rng = random.Random()

    # ─── storage ───────────────────────────────────────────────────────────

    def _load(self) -> dict:
        if self._data is not None:
            return self._data
        if not self.path.exists():
            self._data = {"templates": [], "results": []}
            self._seed_defaults()
            self._save_unlocked()
            return self._data
        try:
            with self.path.open("r", encoding="utf-8") as f:
                self._data = json.load(f)
        except Exception:
            log.exception("Failed to load %s — starting fresh", self.path)
            self._data = {"templates": [], "results": []}
            self._seed_defaults()
        # Ensure required keys exist on disk-loaded data too.
        self._data.setdefault("templates", [])
        self._data.setdefault("results", [])
        if not any(t.get("skill") == "code" for t in self._data["templates"]):
            self._seed_defaults()
        return self._data

    def _save_unlocked(self) -> None:
        assert self._data is not None
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(self.path.suffix + ".tmp")
        with tmp.open("w", encoding="utf-8") as f:
            json.dump(self._data, f, indent=2, ensure_ascii=False)
        tmp.replace(self.path)

    def _seed_defaults(self) -> None:
        assert self._data is not None
        self._data["templates"].append(
            asdict(
                PromptTemplate(
                    id="coder_v1",
                    skill="code",
                    template=_DEFAULT_CODER_TEMPLATE,
                    parent_id=None,
                    created_at=datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
                    active=True,
                )
            )
        )

    # ─── public API ────────────────────────────────────────────────────────

    def templates_for(self, skill: str, *, active_only: bool = True) -> list[PromptTemplate]:
        with self._lock:
            data = self._load()
            return [
                PromptTemplate(**t)
                for t in data["templates"]
                if t.get("skill") == skill and (not active_only or t.get("active", True))
            ]

    def get(self, template_id: str) -> PromptTemplate | None:
        with self._lock:
            data = self._load()
            for t in data["templates"]:
                if t.get("id") == template_id:
                    return PromptTemplate(**t)
        return None

    def pick(self, skill: str) -> PromptTemplate | None:
        """Epsilon-greedy selection over active templates for `skill`."""
        active = self.templates_for(skill, active_only=True)
        if not active:
            return None
        if len(active) == 1:
            return active[0]

        # Exploration: random pick.
        if self._rng.random() < self.epsilon:
            return self._rng.choice(active)

        # Exploitation: best win rate. Untried beats any "explored to bad".
        stats_by_id = {s.template_id: s for s in self._stats_locked_iter()}
        scored: list[tuple[float, PromptTemplate]] = []
        for t in active:
            s = stats_by_id.get(t.id)
            trials = s.successes + s.failures if s else 0
            if trials < MIN_SAMPLES_FOR_GREEDY:
                # Under-sampled templates outrank ANY known win rate so
                # freshly added/evolved siblings are guaranteed traffic.
                scored.append((float("inf"), t))
            else:
                scored.append((s.win_rate, t))
        scored.sort(key=lambda pair: pair[0], reverse=True)
        return scored[0][1]

    def render(self, skill: str, task: str) -> tuple[str | None, str]:
        """Return (template_id, rendered_prompt). If no template, the task
        flows through unchanged and template_id is None."""
        tpl = self.pick(skill)
        if tpl is None:
            return None, task
        return tpl.id, tpl.render(task)

    def add(self, template: PromptTemplate) -> None:
        with self._lock:
            data = self._load()
            data["templates"].append(asdict(template))
            self._save_unlocked()

    def set_active(self, template_id: str, active: bool) -> bool:
        with self._lock:
            data = self._load()
            for t in data["templates"]:
                if t.get("id") == template_id:
                    t["active"] = active
                    self._save_unlocked()
                    return True
        return False

    def record_outcome(
        self,
        template_id: str,
        task: str,
        outcome: str,
        detail: str = "",
    ) -> None:
        if outcome not in {"success", "failure", "unknown"}:
            outcome = "unknown"
        with self._lock:
            data = self._load()
            data["results"].append(
                asdict(
                    Outcome(
                        template_id=template_id,
                        task=task[:300],
                        outcome=outcome,
                        timestamp=datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
                        detail=detail[:500],
                    )
                )
            )
            # Cap total results so the file doesn't grow unbounded.
            if len(data["results"]) > 2000:
                data["results"] = data["results"][-2000:]
            self._save_unlocked()

    def stats(self) -> list[TemplateStats]:
        with self._lock:
            return list(self._stats_locked_iter())

    def failures_for(self, template_id: str, n: int = 10) -> list[Outcome]:
        with self._lock:
            data = self._load()
            return [
                Outcome(**r)
                for r in data["results"]
                if r.get("template_id") == template_id and r.get("outcome") == "failure"
            ][-n:]

    # ─── internals ─────────────────────────────────────────────────────────

    def _stats_locked_iter(self) -> Iterable[TemplateStats]:
        data = self._load()
        agg: dict[str, dict[str, int]] = {}
        # Outcome values are singular ("success"/"failure"/"unknown"); count
        # keys are plural. Map carefully so we don't misbucket wins as unknowns.
        outcome_to_key = {"success": "successes", "failure": "failures", "unknown": "unknown"}
        for r in data["results"]:
            tid = r.get("template_id")
            if not tid:
                continue
            row = agg.setdefault(tid, {"successes": 0, "failures": 0, "unknown": 0})
            key = outcome_to_key.get(r.get("outcome", "unknown"), "unknown")
            row[key] += 1
        for tid, row in agg.items():
            trials = row["successes"] + row["failures"] + row["unknown"]
            yield TemplateStats(
                template_id=tid,
                trials=trials,
                successes=row["successes"],
                failures=row["failures"],
                unknown=row["unknown"],
            )
