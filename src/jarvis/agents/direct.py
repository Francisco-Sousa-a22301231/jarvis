"""Direct answer agent: smalltalk, greetings, factual one-shot questions.

This is the fallback when the router can't justify a specialized skill. Pure
Haiku call with a tight persona prompt — keeps responses voice-friendly.
"""
from __future__ import annotations

from ..llm import haiku


_PERSONA = (
    "You are Jarvis, a calm and concise voice assistant for a solo developer. "
    "Answer in 1–2 short sentences suitable for text-to-speech. "
    "No markdown, no lists, no emojis. If you don't know, say so briefly."
)


class DirectAgent:
    def execute(self, task: str) -> str:
        return haiku(system=_PERSONA, user=task, max_tokens=150)
