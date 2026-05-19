"""Trello agent: query Doing/Todo lists, create cards.

Two sub-skills route here:
  - trello_query: list cards (optionally filtered by list name)
  - trello_create: create a new card in Todo (or named list)

The agent decides which based on a tiny Haiku classification of the task,
since the router has already done the broad routing.
"""
from __future__ import annotations

import logging
import os

import httpx

from ..llm import haiku

log = logging.getLogger(__name__)

TRELLO_BASE = "https://api.trello.com/1"
TIMEOUT = 10.0


class TrelloAgent:
    def __init__(
        self,
        key: str | None = None,
        token: str | None = None,
        board_id: str | None = None,
    ):
        self.key = key or os.getenv("TRELLO_KEY")
        self.token = token or os.getenv("TRELLO_TOKEN")
        self.board_id = board_id or os.getenv("TRELLO_BOARD_ID")
        if not (self.key and self.token and self.board_id):
            raise RuntimeError(
                "Trello credentials missing. Set TRELLO_KEY, TRELLO_TOKEN, TRELLO_BOARD_ID."
            )

    def _auth(self) -> dict[str, str]:
        return {"key": self.key, "token": self.token}

    def _lists(self) -> list[dict]:
        r = httpx.get(
            f"{TRELLO_BASE}/boards/{self.board_id}/lists",
            params=self._auth(),
            timeout=TIMEOUT,
        )
        r.raise_for_status()
        return r.json()

    def _list_cards(self, list_id: str) -> list[dict]:
        r = httpx.get(
            f"{TRELLO_BASE}/lists/{list_id}/cards",
            params=self._auth(),
            timeout=TIMEOUT,
        )
        r.raise_for_status()
        return r.json()

    # ─── public API ────────────────────────────────────────────────────────

    def execute(self, task: str) -> str:
        """Routed via skill_id (trello_query vs trello_create) — but the
        dispatcher passes both here. We disambiguate via the task verbs."""
        # Cheap intent: if it sounds like creation, create. Else query.
        lower = task.lower()
        create_verbs = (
            "create",
            "add",
            "make",
            "new card",
            "remind me",
            "put on trello",
        )
        if any(v in lower for v in create_verbs):
            return self.create(task)
        return self.query(task)

    def query(self, task: str) -> str:
        lower = task.lower()
        target = None
        for name in ("backlog", "todo", "doing", "in review", "done"):
            if name in lower:
                target = name
                break

        lists = self._lists()
        if target:
            lists = [l for l in lists if target in l["name"].lower()]

        rows: list[str] = []
        for lst in lists:
            for card in self._list_cards(lst["id"]):
                rows.append(f"[{lst['name']}] {card['name']}")

        if not rows:
            return "No matching Trello cards."

        # Haiku makes it sound natural for TTS.
        return haiku(
            system=(
                "Summarize these Trello cards for a voice assistant in 1–3 short sentences. "
                "Mention totals per list when useful. Skip card descriptions. "
                "Tone: calm, factual, no emojis."
            ),
            user="\n".join(rows[:50]),
            max_tokens=180,
        )

    def create(self, task: str) -> str:
        # Use Haiku to extract (name, list) — name should be short and actionable.
        extracted = haiku(
            system=(
                "Extract a Trello card from the user's request. Reply with JSON only:\n"
                '{"name": "<short imperative card title>", "list": "<Backlog|Todo|Doing|In Review|Done>"}\n'
                "If list isn't obvious, use Todo."
            ),
            user=task,
            max_tokens=80,
        )
        import json
        import re

        m = re.search(r"\{.*\}", extracted, re.DOTALL)
        try:
            data = json.loads(m.group(0)) if m else {}
        except (json.JSONDecodeError, AttributeError):
            data = {}
        name = data.get("name") or task.strip()
        list_name = (data.get("list") or "Todo").strip()

        lists = self._lists()
        target = next(
            (l for l in lists if list_name.lower() in l["name"].lower()),
            None,
        )
        if target is None:
            return f"Couldn't find Trello list {list_name!r}."

        r = httpx.post(
            f"{TRELLO_BASE}/cards",
            params={
                **self._auth(),
                "idList": target["id"],
                "name": name,
            },
            timeout=TIMEOUT,
        )
        r.raise_for_status()
        return f"Added '{name}' to {target['name']}."
