"""Calendar agent — two backends:

  - "applescript": macOS Calendar.app via osascript. Zero auth setup, but
    macOS-only and requires Automation permission.
  - "google": Google Calendar API. Cross-platform (works on Windows). Uses
    the shared Google OAuth helper.

`build_calendar_agent(config)` at the bottom returns whichever the user's
config asks for. Default is "google" — it works everywhere.
"""
from __future__ import annotations

import logging
import platform
import subprocess
from typing import TYPE_CHECKING

from ..llm import haiku

if TYPE_CHECKING:
    from ..config import Config

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


def build_calendar_agent(config: "Config"):
    """Return whichever calendar agent matches config.calendar_backend.

    Default is "google" since it works on Windows and Mac alike, and most
    people use Google Calendar regardless of OS.
    """
    backend = config.calendar_backend
    if backend == "applescript":
        return CalendarAgent()
    # Default + explicit "google"
    from .gcalendar import GoogleCalendarAgent

    return GoogleCalendarAgent(
        credentials_path=config.google_credentials_path,
        token_path=config.google_token_path,
    )
