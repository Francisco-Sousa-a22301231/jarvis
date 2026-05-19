"""Static catalog of skills the router can pick from.

Keep this LEAN — every line ships in the router's system prompt on every call.
~250 tokens total is healthy; over 500 and we start losing the low-context win.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Skill:
    id: str
    description: str  # one-line, used in the router prompt


SKILL_CATALOG: tuple[Skill, ...] = (
    Skill(
        id="code",
        description="Write, edit, debug, or test code in a software project. ex: 'add a dark mode toggle', 'fix the login bug'",
    ),
    Skill(
        id="trello_query",
        description="Look up Trello cards, lists, or board state. ex: 'what's in my Doing list', 'show today's tasks'",
    ),
    Skill(
        id="trello_create",
        description="Create a new Trello card. ex: 'add a card to call Pedro tomorrow', 'remind me to fix the bug'",
    ),
    Skill(
        id="calendar",
        description="Read today's calendar events from macOS Calendar. ex: 'what's on my calendar', 'next meeting'",
    ),
    Skill(
        id="mail",
        description="Read unread emails from macOS Mail app. ex: 'any new emails', 'check my inbox'",
    ),
    Skill(
        id="brief",
        description="Combined daily summary of calendar + mail + Trello. ex: 'morning brief', 'catch me up'",
    ),
    Skill(
        id="direct",
        description="Smalltalk, greetings, factual questions, status checks. ex: 'hello', 'are you there', 'what time is it'",
    ),
)


def skill_ids() -> list[str]:
    return [s.id for s in SKILL_CATALOG]


def catalog_lines() -> str:
    return "\n".join(f"- {s.id}: {s.description}" for s in SKILL_CATALOG)
