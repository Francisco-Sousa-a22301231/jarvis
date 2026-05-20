"""Direct answer agent: smalltalk, greetings, factual one-shot questions.

For pure greetings ("hello", "hi", "good morning", ...) we skip the LLM
entirely and return a canned response — saves a ~2 second `claude -p`
spawn on the most common kind of utterance.

Everything else falls through to a Haiku call with a tight persona prompt.
"""
from __future__ import annotations

import random
import re
import time as _time

from ..llm import haiku


_PERSONA = (
    "You are Jarvis, a calm and concise voice assistant for a solo developer. "
    "Answer in 1–2 short sentences suitable for text-to-speech. "
    "No markdown, no lists, no emojis. If you don't know, say so briefly."
)


# Canned smalltalk — matched first, before any LLM call.
# Each entry: (compiled regex, list of possible responses)
_CANNED: list[tuple[re.Pattern[str], list[str]]] = [
    (
        re.compile(r"^\s*(hi|hello|hey)(\s|[!.?,]|$)", re.I),
        ["Hi.", "Hello.", "Hey."],
    ),
    (
        re.compile(r"^\s*good\s+morning\b", re.I),
        ["Good morning.", "Morning."],
    ),
    (
        re.compile(r"^\s*good\s+(afternoon|evening|night)\b", re.I),
        ["Good evening.", "Evening."],
    ),
    (
        re.compile(r"^\s*(thanks|thank you|cheers)\b", re.I),
        ["Anytime.", "You got it.", "Sure."],
    ),
    (
        re.compile(r"\b(are|you)\s+(you|there|online|alive|awake)\b", re.I),
        ["I'm here.", "Yes, listening.", "Right here."],
    ),
    (
        re.compile(r"^\s*what\s+time\s+is\s+it\b", re.I),
        [None],  # special: time string built at call time
    ),
]


class DirectAgent:
    def execute(self, task: str) -> str:
        for pattern, responses in _CANNED:
            if pattern.search(task):
                pick = random.choice(responses)
                if pick is None:
                    # what-time-is-it special
                    return _time.strftime("It's %I:%M %p.").lstrip("0")
                return pick

        # Anything not in the canned set → Haiku.
        return haiku(system=_PERSONA, user=task, max_tokens=150)
