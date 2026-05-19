"""Nickname → email-address lookup.

Loads ~/.jarvis/contacts.toml (or wherever config points). Used by
MailSendAgent to resolve "Pedro" → "pedro@example.com".

Example contacts.toml:

    [contacts]
    pedro = "pedro@example.com"
    mom = "mom@example.com"
    "ana costa" = "ana@example.com"
"""
from __future__ import annotations

import logging
import tomllib
from pathlib import Path

log = logging.getLogger(__name__)


_EMAIL_RE_HINT = "@"


def is_email(value: str) -> bool:
    return _EMAIL_RE_HINT in value and "." in value.split(_EMAIL_RE_HINT, 1)[-1]


def load(path: Path) -> dict[str, str]:
    """Return a case-insensitive nickname → email map, or {} if no file."""
    if not path.exists():
        return {}
    try:
        with path.open("rb") as f:
            data = tomllib.load(f)
    except Exception:
        log.exception("Failed to load contacts %s", path)
        return {}
    raw = data.get("contacts", {})
    return {str(k).strip().lower(): str(v).strip() for k, v in raw.items() if v}


def resolve(name: str, contacts: dict[str, str]) -> str | None:
    """Resolve a nickname to an email. Returns None if not found.

    If `name` is already an email address, returns it unchanged.
    """
    n = name.strip()
    if is_email(n):
        return n
    return contacts.get(n.lower())
