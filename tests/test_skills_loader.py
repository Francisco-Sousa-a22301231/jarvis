"""Custom skills loader tests."""
from __future__ import annotations

from pathlib import Path

import pytest

from jarvis import skills
from jarvis.skills_loader import load_dir


@pytest.fixture(autouse=True)
def restore_catalog():
    snapshot = list(skills.SKILL_CATALOG)
    yield
    skills.SKILL_CATALOG.clear()
    skills.SKILL_CATALOG.extend(snapshot)


def _write_skill(path: Path, name: str, body: str = "return 'ok'") -> None:
    path.write_text(
        f'''
ID = "{name}"
DESCRIPTION = "Example skill."
def execute(task):
    {body}
''',
        encoding="utf-8",
    )


def test_loads_valid_skill(tmp_path: Path):
    _write_skill(tmp_path / "hello.py", "hello")
    agents = load_dir(tmp_path)
    assert "hello" in agents
    assert agents["hello"].execute("anything") == "ok"
    assert "hello" in [s.id for s in skills.SKILL_CATALOG]


def test_skips_missing_id(tmp_path: Path):
    (tmp_path / "bad.py").write_text(
        'DESCRIPTION = "x"\ndef execute(task): return "x"\n', encoding="utf-8"
    )
    agents = load_dir(tmp_path)
    assert "bad" not in agents
    assert agents == {}


def test_skips_wrong_arity(tmp_path: Path):
    (tmp_path / "bad.py").write_text(
        'ID = "bad"\nDESCRIPTION = "x"\ndef execute(): return "x"\n',
        encoding="utf-8",
    )
    assert load_dir(tmp_path) == {}


def test_continues_after_bad_file(tmp_path: Path):
    """One broken skill must not block the rest from loading."""
    (tmp_path / "broken.py").write_text("this is not python !!!", encoding="utf-8")
    _write_skill(tmp_path / "good.py", "good")
    agents = load_dir(tmp_path)
    assert "good" in agents
    assert "broken" not in agents


def test_underscore_files_ignored(tmp_path: Path):
    _write_skill(tmp_path / "_private.py", "private")
    assert load_dir(tmp_path) == {}


def test_missing_dir_returns_empty(tmp_path: Path):
    assert load_dir(tmp_path / "does-not-exist") == {}


def test_skill_exception_caught(tmp_path: Path):
    _write_skill(tmp_path / "boom.py", "boom", body="raise RuntimeError('kaboom')")
    agents = load_dir(tmp_path)
    out = agents["boom"].execute("x")
    assert "failed" in out.lower()
    assert "kaboom" in out


def test_register_replaces_existing_skill():
    """Custom skill with same id as a built-in REPLACES the built-in entry."""
    initial = len(skills.SKILL_CATALOG)
    skills.register(skills.Skill(id="brief", description="Custom brief override"))
    # Same id → no growth in catalog
    assert len(skills.SKILL_CATALOG) == initial
    # Description should now be the custom one
    brief = [s for s in skills.SKILL_CATALOG if s.id == "brief"][0]
    assert brief.description == "Custom brief override"
