"""Multi-project resolution tests."""
from __future__ import annotations

from pathlib import Path

import pytest

from jarvis.projects import Project, resolve_project


@pytest.fixture
def projects():
    return (
        Project(name="mylessons", path=Path("/x/MyLessons"), aliases=("my lessons",)),
        Project(name="jarvis", path=Path("/x/jarvis"), aliases=()),
    )


def test_explicit_in_project(projects):
    p, cleaned = resolve_project("in mylessons add a dark mode toggle", projects)
    assert p.name == "mylessons"
    assert cleaned == "add a dark mode toggle"


def test_alias_match(projects):
    p, cleaned = resolve_project("in my lessons fix the login bug", projects)
    assert p.name == "mylessons"
    assert "my lessons" not in cleaned.lower()


def test_on_project(projects):
    p, cleaned = resolve_project("on jarvis improve the brief composer", projects)
    assert p.name == "jarvis"
    assert "jarvis" not in cleaned.lower()


def test_colon_form(projects):
    p, cleaned = resolve_project("mylessons: refactor the auth module", projects)
    assert p.name == "mylessons"
    assert cleaned == "refactor the auth module"


def test_no_mention_returns_default(projects):
    p, cleaned = resolve_project("add a dark mode toggle to settings", projects)
    assert p.name == "mylessons"  # first = default
    assert cleaned == "add a dark mode toggle to settings"


def test_empty_projects():
    p, cleaned = resolve_project("anything", ())
    assert p is None
    assert cleaned == "anything"


def test_for_the_project(projects):
    p, cleaned = resolve_project("for the mylessons project run the tests", projects)
    assert p.name == "mylessons"
    assert "mylessons" not in cleaned.lower()
