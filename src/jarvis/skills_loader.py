"""Load user-defined skills from ~/.jarvis/skills/*.py at startup.

Each .py file must define three module-level names:

    ID = "weather"
    DESCRIPTION = "Check the weather. ex: 'what's the weather in Cascais'"

    def execute(task: str) -> str:
        ...

Optional:
    REQUIRES_CONFIRM = True

The file is `importlib`-loaded by path (no PYTHONPATH/setup needed). On
failure it logs and skips — one bad skill never breaks daemon startup.

This is a startup-time loader. To hot-reload, restart the daemon. A
filesystem watcher could land later if the workflow demands it.
"""
from __future__ import annotations

import importlib.util
import inspect
import logging
from pathlib import Path
from typing import Callable

from .skills import Skill, register

log = logging.getLogger(__name__)

DEFAULT_SKILLS_DIR = Path.home() / ".jarvis" / "skills"


class _CustomAgent:
    """Wraps a user-supplied execute() function as an Agent."""

    def __init__(self, fn: Callable[[str], str], name: str):
        self._fn = fn
        self._name = name

    def execute(self, task: str) -> str:
        try:
            return self._fn(task)
        except Exception as e:
            log.exception("Custom skill %r raised", self._name)
            return f"Custom skill {self._name!r} failed: {e}"


def load_dir(skills_dir: Path = DEFAULT_SKILLS_DIR) -> dict[str, _CustomAgent]:
    """Scan `skills_dir` for .py files. Return id → agent map. Register each
    in the skill catalog as a side effect.
    """
    if not skills_dir.exists():
        return {}

    agents: dict[str, _CustomAgent] = {}
    for path in sorted(skills_dir.glob("*.py")):
        if path.name.startswith("_"):
            continue
        try:
            mod = _load_module(path)
        except Exception:
            log.exception("Custom skill %s failed to import", path.name)
            continue

        skill_id = getattr(mod, "ID", None)
        description = getattr(mod, "DESCRIPTION", None)
        execute = getattr(mod, "execute", None)
        if not (isinstance(skill_id, str) and isinstance(description, str)):
            log.warning(
                "Custom skill %s missing ID/DESCRIPTION (str). Skipped.", path.name
            )
            continue
        if not callable(execute):
            log.warning("Custom skill %s missing execute() callable. Skipped.", path.name)
            continue
        # Be defensive about the signature: execute(task: str) -> str.
        try:
            sig = inspect.signature(execute)
            if len(sig.parameters) != 1:
                log.warning(
                    "Custom skill %s: execute() must take exactly 1 arg (task: str). Skipped.",
                    path.name,
                )
                continue
        except (TypeError, ValueError):
            pass  # bound methods / C builtins — assume OK

        requires_confirm = bool(getattr(mod, "REQUIRES_CONFIRM", False))
        register(
            Skill(
                id=skill_id,
                description=description,
                requires_confirm=requires_confirm,
            )
        )
        agents[skill_id] = _CustomAgent(execute, name=skill_id)
        log.info("Loaded custom skill %r from %s", skill_id, path.name)

    return agents


def _load_module(path: Path):
    spec = importlib.util.spec_from_file_location(f"_jarvis_skill_{path.stem}", path)
    if spec is None or spec.loader is None:
        raise ImportError(f"Couldn't build spec for {path}")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)  # type: ignore[union-attr]
    return mod
