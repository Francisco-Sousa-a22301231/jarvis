"""Memory-query agent: 'what did I ask earlier?'.

Reads the recent-utterances file written by Phase 4's Memory module and asks
Haiku to summarize for voice. Cost is bounded: the memory file caps at ~10
entries and we only feed the last ~6 to Haiku.
"""
from __future__ import annotations

from ..llm import haiku
from ..memory import Memory


class MemoryQueryAgent:
    def __init__(self, memory: Memory | None = None):
        self.memory = memory or Memory()

    def execute(self, task: str) -> str:
        snippet = self.memory.recent_snippet(n=6)
        if not snippet:
            return "Nothing in recent memory yet."

        return haiku(
            system=(
                "Summarize the user's recent interactions with their voice "
                "assistant for playback over TTS. 1-3 short sentences. "
                "Mention what they asked about, in chronological order, "
                "newest last. No emojis, no markdown."
            ),
            user=snippet,
            max_tokens=200,
            cache=False,  # different every call
        )
