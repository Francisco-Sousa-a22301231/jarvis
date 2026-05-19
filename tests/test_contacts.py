"""Contacts loader tests."""
from __future__ import annotations

from pathlib import Path

from jarvis import contacts


def test_is_email():
    assert contacts.is_email("pedro@example.com")
    assert not contacts.is_email("pedro")
    assert not contacts.is_email("not even close")


def test_load_returns_lowercased_keys(tmp_path: Path):
    p = tmp_path / "contacts.toml"
    p.write_text(
        '[contacts]\nPedro = "p@x.com"\n"Ana Costa" = "a@x.com"\n',
        encoding="utf-8",
    )
    loaded = contacts.load(p)
    assert loaded == {"pedro": "p@x.com", "ana costa": "a@x.com"}


def test_load_missing_file_returns_empty(tmp_path: Path):
    assert contacts.load(tmp_path / "nonexistent.toml") == {}


def test_resolve_email_passthrough():
    assert contacts.resolve("alice@x.com", {}) == "alice@x.com"


def test_resolve_nickname():
    assert contacts.resolve("Pedro", {"pedro": "p@x.com"}) == "p@x.com"


def test_resolve_unknown_returns_none():
    assert contacts.resolve("Unknown", {"pedro": "p@x.com"}) is None
