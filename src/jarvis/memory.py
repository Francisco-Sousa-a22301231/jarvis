"""Recent-utterance memory for anaphora resolution.

Stores the last N (transcript, skill, result) tuples in a single markdown file
at ~/.jarvis/memory/recent.md. The router only loads it when the new
transcript looks anaphoric (contains 'it', 'that', 'same', 'again',
'those', 'them') — otherwise we pay zero memory tokens.

This keeps the low-context discipline: history is opt-in per utterance.
"""
from __future__ import annotations

import logging
import re
import threading
from datetime import datetime
from pathlib import Path

log = logging.getLogger(__name__)

DEFAULT_PATH = Path.home() / ".jarvis" / "memory" / "recent.md"
MAX_ENTRIES = 10

# A word-boundary match on pronouns/anaphora that genuinely need prior context.
# Tight on purpose — false positives cost a Haiku call with extra tokens.
_ANAPHORA_RE = re.compile(
    r"\b(it|that|those|them|this|same(?: thing)?|again|like (?:that|before))\b",
    re.I,
)


def needs_history(transcript: str) -> bool:
    """Return True iff the transcript references something from the past."""
    return bool(_ANAPHORA_RE.search(transcript))


class Memory:
    def __init__(self, path: Path | None = None, max_entries: int = MAX_ENTRIES):
        self.path = path or DEFAULT_PATH
        self.max_entries = max_entries
        self._lock = threading.Lock()

    def append(self, transcript: str, skill: str, result: str) -> None:
        """Append one entry. Trims oldest if we exceed max_entries."""
        entry = self._format_entry(transcript, skill, result)
        with self._lock:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            entries = self._read_entries()
            entries.append(entry)
            if len(entries) > self.max_entries:
                entries = entries[-self.max_entries :]
            self.path.write_text("\n\n".join(entries) + "\n", encoding="utf-8")

    def recent_snippet(self, n: int = 2) -> str:
        """Return the last `n` entries as a compact string, or '' if none."""
        with self._lock:
            entries = self._read_entries()
        if not entries:
            return ""
        # Strip the date headers — we only need the You/Jarvis lines for context.
        compact = []
        for e in entries[-n:]:
            for line in e.splitlines():
                if line.startswith("You:") or line.startswith("Jarvis:"):
                    compact.append(line)
        return "\n".join(compact)

    def clear(self) -> None:
        with self._lock:
            if self.path.exists():
                self.path.unlink()

    # ─── internals ─────────────────────────────────────────────────────────

    @staticmethod
    def _format_entry(transcript: str, skill: str, result: str) -> str:
        ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        # Trim long results so memory doesn't grow unbounded.
        result_clip = result.replace("\n", " ").strip()
        if len(result_clip) > 200:
            result_clip = result_clip[:197] + "..."
        return (
            f"## {ts} [{skill}]\n"
            f"You: {transcript.strip()}\n"
            f"Jarvis: {result_clip}"
        )

    def _read_entries(self) -> list[str]:
        if not self.path.exists():
            return []
        try:
            text = self.path.read_text(encoding="utf-8")
        except OSError:
            return []
        # Entries are separated by blank lines; each entry starts with '## '.
        chunks = [c.strip() for c in text.split("\n\n") if c.strip().startswith("## ")]
        return chunks
