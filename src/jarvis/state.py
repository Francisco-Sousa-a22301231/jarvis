"""Daemon state tracker for the orb UI.

A tiny, thread-safe singleton that the loop updates at every state
transition. The orb HTTP server reads it (and the orb HTML polls
the server). Also mirrors state to ~/.jarvis/state.json for any external
tool that wants to inspect it.
"""
from __future__ import annotations

import json
import logging
import threading
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path

log = logging.getLogger(__name__)

DEFAULT_PATH = Path.home() / ".jarvis" / "state.json"


class JarvisState(str, Enum):
    OFFLINE = "offline"      # daemon not running / shutting down
    BOOTING = "booting"      # loading models, starting server
    IDLE = "idle"            # waiting for the wake word
    LISTENING = "listening"  # actively recording an utterance
    THINKING = "thinking"    # transcribing / routing / dispatching
    SPEAKING = "speaking"    # TTS playing


class StateTracker:
    def __init__(self, path: Path | None = None):
        self.path = path or DEFAULT_PATH
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._state: JarvisState = JarvisState.OFFLINE
        self._text: str = ""
        self._updated_at = datetime.now(timezone.utc)
        # Persist initial state so anything watching the file sees a
        # consistent value before the daemon's first transition.
        self._write_unlocked()

    def set(self, state: JarvisState, text: str = "") -> None:
        with self._lock:
            self._state = state
            self._text = text[:200]
            self._updated_at = datetime.now(timezone.utc)
            self._write_unlocked()
        log.debug("state: %s%s", state.value, f" — {text[:60]}" if text else "")

    def snapshot(self) -> dict:
        with self._lock:
            return {
                "state": self._state.value,
                "text": self._text,
                "updated_at": self._updated_at.isoformat(),
            }

    def _write_unlocked(self) -> None:
        payload = {
            "state": self._state.value,
            "text": self._text,
            "updated_at": self._updated_at.isoformat(),
        }
        try:
            tmp = self.path.with_suffix(self.path.suffix + ".tmp")
            tmp.write_text(json.dumps(payload), encoding="utf-8")
            tmp.replace(self.path)
        except OSError:
            log.exception("Couldn't persist state to %s", self.path)
