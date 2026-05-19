"""Watcher tests. Mocks Gmail service so no real API calls."""
from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

from jarvis import watcher


def test_load_save_state_roundtrip(tmp_path: Path):
    path = tmp_path / "state.json"
    watcher._save_state(path, {"last_mail_id": "abc"})
    loaded = watcher._load_state(path)
    assert loaded == {"last_mail_id": "abc"}


def test_load_missing_state(tmp_path: Path):
    assert watcher._load_state(tmp_path / "nope.json") == {}


def test_skipped_when_no_vips(tmp_path: Path):
    result = watcher.watch_mail(
        google_credentials_path=tmp_path / "c.json",
        google_token_path=tmp_path / "t.json",
        vip_senders=(),
        state_path=tmp_path / "state.json",
    )
    assert result.notified == 0
    assert result.skipped_reason is not None


def test_skipped_when_gmail_not_configured(tmp_path: Path):
    """No credentials file → graceful skip, not a crash."""
    result = watcher.watch_mail(
        google_credentials_path=tmp_path / "missing.json",
        google_token_path=tmp_path / "t.json",
        vip_senders=("important@x.com",),
        state_path=tmp_path / "state.json",
    )
    assert result.notified == 0
    assert result.skipped_reason is not None


def test_notifies_new_vip_mail(tmp_path: Path):
    """End-to-end mock: query returns one message, we notify, state persists."""
    fake_service = MagicMock()
    fake_service.users().messages().list().execute.return_value = {
        "messages": [{"id": "m1"}]
    }
    fake_service.users().messages().get().execute.return_value = {
        "payload": {"headers": [
            {"name": "From", "value": "important@x.com"},
            {"name": "Subject", "value": "Hello"},
        ]}
    }

    with patch("jarvis.agents.gmail.GmailAgent._service_or_error",
               return_value=(fake_service, None)), patch(
        "jarvis.watcher._notify", return_value=True
    ) as notify:
        result = watcher.watch_mail(
            google_credentials_path=tmp_path / "c.json",
            google_token_path=tmp_path / "t.json",
            vip_senders=("important@x.com",),
            state_path=tmp_path / "state.json",
        )
    assert result.notified == 1
    notify.assert_called_once()
    state = json.loads((tmp_path / "state.json").read_text(encoding="utf-8"))
    assert state["last_mail_id"] == "m1"
