"""Calendar agent: read today's events from macOS Calendar via AppleScript.

macOS-only. On first run, macOS asks for Automation permission for Calendar
(System Settings → Privacy & Security → Automation). The grant attaches to
the python binary that runs Jarvis.
"""
from __future__ import annotations

import logging
import platform
import subprocess

from ..llm import haiku

log = logging.getLogger(__name__)


_APPLESCRIPT_TODAY = r"""
set out to ""
tell application "Calendar"
    set today_d to current date
    set hours of today_d to 0
    set minutes of today_d to 0
    set seconds of today_d to 0
    set tomorrow_d to today_d + (1 * days)
    repeat with cal in calendars
        try
            set evs to (every event of cal whose start date is greater than or equal to today_d and start date is less than tomorrow_d)
            repeat with e in evs
                set t to time string of (start date of e)
                set out to out & t & " — " & (summary of e) & linefeed
            end repeat
        end try
    end repeat
end tell
return out
"""


class CalendarAgent:
    def execute(self, task: str) -> str:
        if platform.system() != "Darwin":
            return "Calendar agent only works on macOS."

        try:
            proc = subprocess.run(
                ["osascript", "-e", _APPLESCRIPT_TODAY],
                capture_output=True,
                text=True,
                timeout=15,
            )
        except FileNotFoundError:
            return "osascript not found. Are you on macOS?"
        except subprocess.TimeoutExpired:
            return "Calendar query timed out."

        if proc.returncode != 0:
            err = proc.stderr.strip()
            if "not authorized" in err.lower() or "1743" in err:
                return (
                    "Need permission to read Calendar. "
                    "Grant Automation access in System Settings."
                )
            log.error("osascript failed: %s", err)
            return "Couldn't read your calendar."

        events = proc.stdout.strip()
        if not events:
            return "Nothing on your calendar today."

        return haiku(
            system=(
                "Summarize today's calendar events for a voice assistant in 1–2 short "
                "sentences. Mention count and the next event by name. Tone: calm, "
                "factual, no emojis."
            ),
            user=events,
            max_tokens=150,
        )

    def raw_events(self) -> str:
        """Used by the brief composer — returns raw event lines, no Haiku."""
        if platform.system() != "Darwin":
            return ""
        try:
            proc = subprocess.run(
                ["osascript", "-e", _APPLESCRIPT_TODAY],
                capture_output=True,
                text=True,
                timeout=15,
            )
            if proc.returncode != 0:
                return ""
            return proc.stdout.strip()
        except Exception:
            return ""
