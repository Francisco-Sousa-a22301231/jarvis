"""Proactive watcher — macOS notifications for new VIP mail, imminent
calendar events, and new Trello cards on a watched list.

Each source has its own `watch_*()` function that:
  - Loads watcher-state.json
  - Polls its source
  - Notifies via osascript on new items it hasn't seen before
  - Persists what it saw

Run via `jarvis watch` (CLI / launchd). State at ~/.jarvis/watcher-state.json
is shared across sources but namespaced by key so they don't collide.
"""
from __future__ import annotations

import hashlib
import json
import logging
import platform
import shutil
import subprocess
from dataclasses import dataclass
from datetime import datetime, timedelta
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
    """Post a desktop notification. Returns True if sent.

    macOS:   osascript display notification (banner).
    Windows: PowerShell BurntToast if installed, else log + system beep.
    Other:   notify-send if available, else log.
    """
    system = platform.system()
    if system == "Darwin":
        return _notify_macos(title, body)
    if system == "Windows":
        return _notify_windows(title, body)
    if system == "Linux":
        return _notify_linux(title, body)
    log.info("[notify] %s — %s", title, body)
    return False


def _notify_macos(title: str, body: str) -> bool:
    if not shutil.which("osascript"):
        return False
    safe_title = title.replace('"', '\\"')
    safe_body = body.replace('"', '\\"')
    script = f'display notification "{safe_body}" with title "{safe_title}"'
    try:
        subprocess.run(
            ["osascript", "-e", script], capture_output=True, timeout=10, check=False
        )
        return True
    except Exception:
        log.exception("macOS notify failed")
        return False


def _notify_windows(title: str, body: str) -> bool:
    """Try BurntToast → fall back to console message + system beep."""
    powershell = shutil.which("pwsh.exe") or shutil.which("powershell.exe")
    if powershell is not None:
        # Single-quoted PowerShell strings: escape ' as ''
        t = title.replace("'", "''")
        b = body.replace("'", "''")
        # Use BurntToast if available; otherwise this command will fail silently
        # and we'll fall through to the console+beep path.
        script = (
            "if (Get-Module -ListAvailable -Name BurntToast) {"
            f"  New-BurntToastNotification -Text '{t}', '{b}'"
            "} else { exit 1 }"
        )
        try:
            proc = subprocess.run(
                [powershell, "-NoProfile", "-NonInteractive", "-Command", script],
                capture_output=True,
                timeout=10,
                check=False,
            )
            if proc.returncode == 0:
                return True
        except Exception:
            log.exception("BurntToast attempt failed")

    # Fallback: log line + system beep so a backgrounded daemon still gives a cue.
    log.info("[notify] %s — %s", title, body)
    try:
        import winsound

        winsound.MessageBeep()
        return True
    except Exception:
        return False


def _notify_linux(title: str, body: str) -> bool:
    if shutil.which("notify-send"):
        try:
            subprocess.run(
                ["notify-send", title, body], capture_output=True, timeout=10, check=False
            )
            return True
        except Exception:
            pass
    log.info("[notify] %s — %s", title, body)
    return False


def watch_mail(
    google_credentials_path: Path,
    google_token_path: Path,
    vip_senders: tuple[str, ...],
    state_path: Path = DEFAULT_STATE_PATH,
    max_messages: int = 8,
) -> WatcherResult:
    """One-shot scan for VIP mail newer than last seen id."""
    if not vip_senders:
        return WatcherResult(notified=0, checked=0, skipped_reason="no VIP senders configured")

    from .agents.gmail import GmailAgent

    agent = GmailAgent(
        credentials_path=google_credentials_path,
        token_path=google_token_path,
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


# ─── Calendar lead-time watcher ────────────────────────────────────────────

_APPLESCRIPT_UPCOMING = r"""
set out to ""
tell application "Calendar"
    set now_d to current date
    set window_d to now_d + (lead_min * minutes)
    repeat with cal in calendars
        try
            set evs to (every event of cal whose start date is greater than or equal to now_d and start date is less than window_d)
            repeat with e in evs
                set s to start date of e
                set out to out & (uid of e) & "|" & (time string of s) & "|" & (summary of e) & linefeed
            end repeat
        end try
    end repeat
end tell
return out
"""


def watch_calendar(
    lead_minutes: int,
    *,
    backend: str = "google",
    google_credentials_path: Path | None = None,
    google_token_path: Path | None = None,
    state_path: Path = DEFAULT_STATE_PATH,
) -> WatcherResult:
    """Notify for events starting within `lead_minutes`, once each.

    backend="google": queries Google Calendar (cross-platform).
    backend="applescript": macOS Calendar.app via osascript.
    """
    if lead_minutes <= 0:
        return WatcherResult(notified=0, checked=0, skipped_reason="calendar watcher disabled")

    if backend == "google":
        if not (google_credentials_path and google_token_path):
            return WatcherResult(
                notified=0, checked=0,
                skipped_reason="calendar watcher needs google_credentials_path/token_path",
            )
        return _watch_calendar_google(
            lead_minutes,
            google_credentials_path,
            google_token_path,
            state_path,
        )

    if platform.system() != "Darwin":
        return WatcherResult(
            notified=0, checked=0,
            skipped_reason="applescript calendar needs macOS — try backend='google'",
        )
    return _watch_calendar_applescript(lead_minutes, state_path)


def _watch_calendar_applescript(lead_minutes: int, state_path: Path) -> WatcherResult:
    script = _APPLESCRIPT_UPCOMING.replace("lead_min", str(lead_minutes))
    try:
        proc = subprocess.run(
            ["osascript", "-e", script],
            capture_output=True,
            text=True,
            timeout=15,
            check=False,
        )
    except FileNotFoundError:
        return WatcherResult(notified=0, checked=0, skipped_reason="osascript not found")
    if proc.returncode != 0:
        return WatcherResult(
            notified=0, checked=0,
            skipped_reason=f"calendar: {proc.stderr.strip()[:140]}",
        )

    state = _load_state(state_path)
    seen_set = set(state.get("calendar_notified", []))

    notified = 0
    fresh_seen: list[str] = []
    rows = [line for line in proc.stdout.splitlines() if line.strip()]
    for row in rows:
        parts = row.split("|", 2)
        if len(parts) < 3:
            continue
        uid, time_str, summary = parts
        key = uid or hashlib.sha1(f"{summary}|{time_str}".encode()).hexdigest()[:12]
        fresh_seen.append(key)
        if key in seen_set:
            continue
        if _notify(f"Soon: {time_str}", summary[:160]):
            notified += 1

    state["calendar_notified"] = fresh_seen
    _save_state(state_path, state)
    return WatcherResult(notified=notified, checked=len(rows))


def _watch_calendar_google(
    lead_minutes: int,
    google_credentials_path: Path,
    google_token_path: Path,
    state_path: Path,
) -> WatcherResult:
    from .agents.gcalendar import GoogleCalendarAgent

    agent = GoogleCalendarAgent(
        credentials_path=google_credentials_path,
        token_path=google_token_path,
    )
    items = agent.upcoming_items(lead_minutes=lead_minutes)
    if not items:
        # Could be empty calendar OR auth failure — distinguish via service probe
        _, err = agent._service_or_error()
        if err:
            return WatcherResult(notified=0, checked=0, skipped_reason=err)
        return WatcherResult(notified=0, checked=0)

    state = _load_state(state_path)
    seen_set = set(state.get("calendar_notified", []))

    notified = 0
    fresh_seen: list[str] = []
    from datetime import datetime as _dt

    for ev in items:
        ev_id = ev.get("id") or hashlib.sha1(
            (ev.get("summary", "") + ev.get("start", {}).get("dateTime", "")).encode()
        ).hexdigest()[:12]
        fresh_seen.append(ev_id)
        if ev_id in seen_set:
            continue
        summary = ev.get("summary", "(no title)")
        start_obj = ev.get("start", {})
        if "dateTime" in start_obj:
            try:
                dt = _dt.fromisoformat(start_obj["dateTime"].replace("Z", "+00:00"))
                time_str = dt.astimezone().strftime("%H:%M")
            except (ValueError, TypeError):
                time_str = "?"
        else:
            time_str = "all-day"
        if _notify(f"Soon: {time_str}", summary[:160]):
            notified += 1

    state["calendar_notified"] = fresh_seen
    _save_state(state_path, state)
    return WatcherResult(notified=notified, checked=len(items))


# ─── Trello list-move watcher ──────────────────────────────────────────────

def watch_trello(
    list_name: str,
    state_path: Path = DEFAULT_STATE_PATH,
) -> WatcherResult:
    """Notify when a card lands in `list_name` (default: 'Doing')."""
    if not list_name:
        return WatcherResult(notified=0, checked=0, skipped_reason="no trello list configured")
    try:
        from .agents.trello import TrelloAgent

        agent = TrelloAgent()
    except RuntimeError as e:
        return WatcherResult(notified=0, checked=0, skipped_reason=str(e))

    try:
        lists = agent._lists()
    except Exception as e:
        log.exception("Trello watcher: list fetch failed")
        return WatcherResult(notified=0, checked=0, skipped_reason=f"trello: {e}")

    target = next((l for l in lists if list_name.lower() in l["name"].lower()), None)
    if target is None:
        return WatcherResult(
            notified=0, checked=0,
            skipped_reason=f"Trello list {list_name!r} not found",
        )

    try:
        cards = agent._list_cards(target["id"])
    except Exception as e:
        return WatcherResult(notified=0, checked=0, skipped_reason=f"trello: {e}")

    state = _load_state(state_path)
    seen: set[str] = set(state.get("trello_doing_ids", []))
    current_ids = [c["id"] for c in cards]

    notified = 0
    for card in cards:
        if card["id"] in seen:
            continue
        if _notify(f"Trello → {target['name']}", card["name"][:160]):
            notified += 1

    state["trello_doing_ids"] = current_ids
    _save_state(state_path, state)
    return WatcherResult(notified=notified, checked=len(cards))


# ─── Aggregator (used by `jarvis watch`) ───────────────────────────────────

@dataclass
class WatchRun:
    mail: WatcherResult
    calendar: WatcherResult
    trello: WatcherResult

    @property
    def total_notified(self) -> int:
        return self.mail.notified + self.calendar.notified + self.trello.notified


def run_all(
    *,
    google_credentials_path: Path,
    google_token_path: Path,
    vip_senders: tuple[str, ...],
    calendar_backend: str,
    calendar_lead_minutes: int,
    trello_watch_list: str,
    state_path: Path = DEFAULT_STATE_PATH,
) -> WatchRun:
    return WatchRun(
        mail=watch_mail(
            google_credentials_path=google_credentials_path,
            google_token_path=google_token_path,
            vip_senders=vip_senders,
            state_path=state_path,
        ),
        calendar=watch_calendar(
            lead_minutes=calendar_lead_minutes,
            backend=calendar_backend,
            google_credentials_path=google_credentials_path,
            google_token_path=google_token_path,
            state_path=state_path,
        ),
        trello=watch_trello(
            list_name=trello_watch_list,
            state_path=state_path,
        ),
    )
