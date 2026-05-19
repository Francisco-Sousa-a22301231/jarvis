"""Google Calendar agent + watcher path tests. All mocks — no API calls."""
from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

from jarvis.agents.gcalendar import GoogleCalendarAgent


def test_service_error_returned_as_string(tmp_path: Path):
    agent = GoogleCalendarAgent(
        credentials_path=tmp_path / "missing.json",
        token_path=tmp_path / "token.json",
    )
    out = agent.execute("today")
    assert "missing" in out.lower() or "couldn't" in out.lower()


def test_fetch_today_returns_lines(tmp_path: Path):
    fake = MagicMock()
    fake.events().list().execute.return_value = {
        "items": [
            {
                "summary": "Standup",
                "start": {"dateTime": "2026-05-19T09:00:00+01:00"},
            },
            {
                "summary": "Project review",
                "start": {"dateTime": "2026-05-19T14:30:00+01:00"},
            },
        ]
    }
    agent = GoogleCalendarAgent(
        credentials_path=tmp_path / "c.json",
        token_path=tmp_path / "t.json",
    )
    with patch.object(agent, "_service_or_error", return_value=(fake, None)):
        raw = agent.raw_events()
    assert "Standup" in raw
    assert "Project review" in raw


def test_all_day_event_formatted(tmp_path: Path):
    fake = MagicMock()
    fake.events().list().execute.return_value = {
        "items": [{"summary": "Holiday", "start": {"date": "2026-05-19"}}]
    }
    agent = GoogleCalendarAgent(
        credentials_path=tmp_path / "c.json",
        token_path=tmp_path / "t.json",
    )
    with patch.object(agent, "_service_or_error", return_value=(fake, None)):
        raw = agent.raw_events()
    assert "all-day" in raw
    assert "Holiday" in raw


def test_upcoming_items(tmp_path: Path):
    fake = MagicMock()
    fake.events().list().execute.return_value = {
        "items": [{"id": "x1", "summary": "Soon", "start": {"dateTime": "2026-05-19T10:00:00+01:00"}}]
    }
    agent = GoogleCalendarAgent(
        credentials_path=tmp_path / "c.json",
        token_path=tmp_path / "t.json",
    )
    with patch.object(agent, "_service_or_error", return_value=(fake, None)):
        items = agent.upcoming_items(lead_minutes=15)
    assert len(items) == 1
    assert items[0]["summary"] == "Soon"
