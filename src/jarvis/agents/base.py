"""Agent protocol.

An agent does one job. It receives a task string (cleaned by the router),
does whatever, and returns a short, speech-ready string for TTS.

Errors should be returned as strings ("Couldn't reach Trello: ..."), not
raised — the dispatcher will catch raises but a clean string is friendlier.
"""
from __future__ import annotations

from typing import Protocol


class Agent(Protocol):
    def execute(self, task: str) -> str:
        ...
