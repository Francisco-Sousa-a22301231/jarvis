"""Proactive watcher — fires macOS notifications for new VIP mail.

Runs once and exits. Schedule it from launchd every N minutes (see
launchd/com.francisco.jarvis-watcher.plist). State (last seen mail id /
last check timestamp) is persisted at ~/.jarvis/watcher-state.json so we
don't double-notify.

Phase 5 covers mail-from-VIPs only. Calendar lead-time and Trello-list
moves are tracked in the Phase 6 backlog.
"""
from __future__ import annotations

import json
import logging
import platform
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

log = logging.getLogger(__name__)

DEFAULT_STATE_PATH = Path.home() / ".jarvis" / "watcher-state.json"


@dataclass
class WatcherResult:
    notified: int
    checked: int
    skipped_reason: str | None = None


def _load_state(path: Path) -> dict:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        log.exception("Couldn't read watcher state %s", path)
        return {}


def _save_state(path: Path, state: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state, indent=2), encoding="utf-8")


def _notify(title: str, body: str) -> bool:
    """Post a macOS notification. Returns True if sent."""
    if platform.system() != "Darwin":
        log.info("[notify on non-mac] %s — %s", title, body)
        return False
    if not shutil.which("osascript"):
        return False
    # Escape double quotes in user-supplied strings.
    safe_title = title.replace('"', '\\"')
    safe_body = body.replace('"', '\\"')
    script = f'display notification "{safe_body}" with title "{safe_title}"'
    try:
        subprocess.run(
            ["osascript", "-e", script],
            capture_output=True,
            timeout=10,
            check=False,
        )
        return True
    except Exception:
        log.exception("notify failed")
        return False


def watch_mail(
    gmail_credentials_path: Path,
    gmail_token_path: Path,
    vip_senders: tuple[str, ...],
    state_path: Path = DEFAULT_STATE_PATH,
    max_messages: int = 8,
) -> WatcherResult:
    """One-shot scan for VIP mail newer than last seen id."""
    if not vip_senders:
        return WatcherResult(notified=0, checked=0, skipped_reason="no VIP senders configured")

    from .agents.gmail import GmailAgent

    agent = GmailAgent(
        credentials_path=gmail_credentials_path,
        token_path=gmail_token_path,
        max_results=max_messages,
    )
    service, err = agent._service_or_error()
    if err is not None:
        return WatcherResult(notified=0, checked=0, skipped_reason=err)

    state = _load_state(state_path)
    last_id = state.get("last_mail_id")

    # Filter Gmail-side by sender — cheaper than fetching everything and filtering locally.
    from_query = " OR ".join(f"from:{v}" for v in vip_senders)
    query = f"({from_query}) is:unread"
    resp = service.users().messages().list(
        userId="me", q=query, maxResults=max_messages
    ).execute()
    msg_ids = [m["id"] for m in resp.get("messages", [])]

    notified = 0
    newest_id_seen = last_id
    for mid in msg_ids:
        if mid == last_id:
            break  # we've caught up to the last seen
        msg = service.users().messages().get(
            userId="me",
            id=mid,
            format="metadata",
            metadataHeaders=["From", "Subject"],
        ).execute()
        headers = {h["name"]: h["value"] for h in msg.get("payload", {}).get("headers", [])}
        sender = headers.get("From", "?")
        subject = headers.get("Subject", "(no subject)")
        if _notify(f"VIP: {sender}", subject[:160]):
            notified += 1
        if newest_id_seen is None or mid != last_id:
            newest_id_seen = newest_id_seen if newest_id_seen != last_id else mid
        # Track newest of this batch
        if msg_ids[0] == mid:
            newest_id_seen = mid

    # If we saw any messages, the first in the list is the newest.
    if msg_ids:
        newest_id_seen = msg_ids[0]

    state["last_mail_id"] = newest_id_seen
    _save_state(state_path, state)
    return WatcherResult(notified=notified, checked=len(msg_ids))
