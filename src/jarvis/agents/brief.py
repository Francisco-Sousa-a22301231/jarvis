"""Brief composer: combines Trello, Calendar, and Mail into one summary.

Strategy for context efficiency:
  1. Pull RAW lines from each source agent (no per-agent Haiku pass).
  2. Concatenate with tiny section headers.
  3. ONE Haiku call composes the final brief.

Net cost: ~1 Haiku call instead of 4 (one per agent + final). ~$0.001 per brief.
"""
from __future__ import annotations

import logging
from typing import Protocol

from ..llm import haiku
from .calendar import CalendarAgent
from .trello import TrelloAgent

log = logging.getLogger(__name__)


class _RawUnreadProvider(Protocol):
    def raw_unread(self) -> str: ...


class BriefAgent:
    def __init__(
        self,
        trello: TrelloAgent | None,
        calendar: CalendarAgent | None,
        mail: _RawUnreadProvider | None,  # MailAgent or GmailAgent
    ):
        self.trello = trello
        self.calendar = calendar
        self.mail = mail

    def execute(self, task: str = "") -> str:
        sections: list[str] = []

        # Trello: cards in Doing (the user's current focus)
        if self.trello is not None:
            try:
                lists = self.trello._lists()
                rows: list[str] = []
                for lst in lists:
                    if "doing" in lst["name"].lower():
                        for card in self.trello._list_cards(lst["id"]):
                            rows.append(f"- {card['name']}")
                if rows:
                    sections.append("Trello (Doing):\n" + "\n".join(rows[:10]))
            except Exception:
                log.exception("Brief: Trello fetch failed")

        # Calendar: today's events
        if self.calendar is not None:
            cal_raw = self.calendar.raw_events()
            if cal_raw:
                sections.append("Calendar today:\n" + cal_raw)

        # Mail: unread
        if self.mail is not None:
            mail_raw = self.mail.raw_unread()
            if mail_raw:
                sections.append("Unread mail:\n" + mail_raw)

        if not sections:
            return "Nothing to brief on — empty calendar, no unread mail, no Doing cards."

        return haiku(
            system=(
                "Compose a morning brief for a solo developer. Combine the sections below "
                "into 3–5 short sentences suitable for text-to-speech. Open with the day's "
                "calendar shape, then call out top mail, then current Trello focus. Tone: "
                "calm, factual, no emojis, no markdown."
            ),
            user="\n\n".join(sections),
            max_tokens=300,
            cache=False,  # input varies daily — no point caching
        )
