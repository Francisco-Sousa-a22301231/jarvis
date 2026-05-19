"""Google Calendar agent.

Cross-platform replacement / alternative to the AppleScript calendar agent.
Uses the unified Google OAuth from google_auth.py — if you have Gmail set
up, this just needs one extra browser consent for the calendar.readonly
scope on the next call.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path

from ..google_auth import build_service
from ..llm import haiku

log = logging.getLogger(__name__)


class GoogleCalendarAgent:
    def __init__(
        self,
        credentials_path: Path,
        token_path: Path,
        calendar_id: str = "primary",
        max_events: int = 20,
    ):
        self.credentials_path = credentials_path
        self.token_path = token_path
        self.calendar_id = calendar_id
        self.max_events = max_events
        self._service = None

    def _service_or_error(self) -> tuple[object | None, str | None]:
        if self._service is not None:
            return self._service, None
        try:
            self._service = build_service(
                "calendar", "v3", self.credentials_path, self.token_path
            )
        except RuntimeError as e:
            return None, str(e)
        return self._service, None

    def _fetch_today(self) -> list[str]:
        service, err = self._service_or_error()
        if err is not None:
            raise RuntimeError(err)

        now_local = datetime.now().astimezone()
        start = now_local.replace(hour=0, minute=0, second=0, microsecond=0)
        end = start + timedelta(days=1)

        resp = (
            service.events()
            .list(
                calendarId=self.calendar_id,
                timeMin=start.isoformat(),
                timeMax=end.isoformat(),
                singleEvents=True,
                orderBy="startTime",
                maxResults=self.max_events,
            )
            .execute()
        )
        rows: list[str] = []
        for ev in resp.get("items", []):
            summary = ev.get("summary", "(no title)")
            start_str = self._format_time(ev.get("start", {}))
            rows.append(f"{start_str} — {summary}")
        return rows

    def _fetch_upcoming(self, lead_minutes: int) -> list[dict]:
        """Events starting within `lead_minutes` from now. Returns raw API items."""
        service, err = self._service_or_error()
        if err is not None:
            raise RuntimeError(err)

        now = datetime.now(timezone.utc)
        until = now + timedelta(minutes=lead_minutes)
        resp = (
            service.events()
            .list(
                calendarId=self.calendar_id,
                timeMin=now.isoformat(),
                timeMax=until.isoformat(),
                singleEvents=True,
                orderBy="startTime",
                maxResults=self.max_events,
            )
            .execute()
        )
        return resp.get("items", [])

    @staticmethod
    def _format_time(start_obj: dict) -> str:
        # "dateTime" for timed events, "date" for all-day.
        if "dateTime" in start_obj:
            try:
                dt = datetime.fromisoformat(start_obj["dateTime"].replace("Z", "+00:00"))
                return dt.astimezone().strftime("%H:%M")
            except (ValueError, TypeError):
                return start_obj.get("dateTime", "?")
        if "date" in start_obj:
            return "all-day"
        return "?"

    # ─── Agent protocol ─────────────────────────────────────────────────────

    def execute(self, task: str) -> str:
        try:
            rows = self._fetch_today()
        except RuntimeError as e:
            return str(e)
        except Exception:
            log.exception("Google Calendar fetch failed")
            return "Couldn't reach Google Calendar."

        if not rows:
            return "Nothing on your calendar today."

        return haiku(
            system=(
                "Summarize today's calendar events for a voice assistant in 1–2 short "
                "sentences. Mention count and the next event by name. Tone: calm, "
                "factual, no emojis."
            ),
            user="\n".join(rows),
            max_tokens=150,
        )

    def raw_events(self) -> str:
        """For the brief composer — raw event lines, no Haiku pass."""
        try:
            return "\n".join(self._fetch_today())
        except Exception:
            return ""

    # ─── Used by the watcher ───────────────────────────────────────────────

    def upcoming_items(self, lead_minutes: int) -> list[dict]:
        try:
            return self._fetch_upcoming(lead_minutes)
        except Exception:
            log.exception("Google Calendar upcoming fetch failed")
            return []
