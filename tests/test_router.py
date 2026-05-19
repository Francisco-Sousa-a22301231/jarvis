"""Router parsing tests. Mocks the Haiku call so no API key needed."""
from __future__ import annotations

from unittest.mock import patch

from jarvis import router
from jarvis.skills import skill_ids


def _patch_haiku(reply: str):
    return patch.object(router, "haiku", return_value=reply)


def test_route_parses_clean_json():
    with _patch_haiku('{"skill": "code", "task": "add dark mode toggle"}'):
        r = router.route("add a dark mode toggle")
    assert r.skill == "code"
    assert r.task == "add dark mode toggle"


def test_route_strips_markdown_fences():
    fenced = '```json\n{"skill": "calendar", "task": "show today\'s events"}\n```'
    with _patch_haiku(fenced):
        r = router.route("what's on my calendar")
    assert r.skill == "calendar"


def test_route_falls_back_to_direct_on_unknown_skill():
    with _patch_haiku('{"skill": "totally_invented", "task": "x"}'):
        r = router.route("...")
    assert r.skill == "direct"


def test_route_falls_back_on_garbage():
    with _patch_haiku("not json at all"):
        r = router.route("hello there")
    assert r.skill == "direct"
    assert r.task == "hello there"


def test_all_catalog_ids_are_distinct():
    ids = skill_ids()
    assert len(ids) == len(set(ids))
