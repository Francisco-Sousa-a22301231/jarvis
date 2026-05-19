"""Mail agent: read unread inbox.

Two backends, selected via config's `mail.backend`:

  - "applescript" (default): reads macOS Mail.app via osascript. Zero auth
    setup but only works on macOS with Mail.app actually running.
  - "gmail":  uses the Gmail OAuth agent in agents/gmail.py. Cross-platform
    but requires a one-time OAuth setup (see Phase 4 README section).

The `build_mail_agent(config)` factory at the bottom returns whichever the
config asks for.
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


_APPLESCRIPT_UNREAD = r"""
set out to ""
tell application "Mail"
    set acct_list to every account
    set total to 0
    repeat with a in acct_list
        try
            set inbox_msgs to (messages of mailbox "INBOX" of a whose read status is false)
            repeat with m in inbox_msgs
                set total to total + 1
                if total > 8 then exit repeat
                set s to subject of m
                set f to sender of m
                set out to out & f & " | " & s & linefeed
            end repeat
        end try
        if total > 8 then exit repeat
    end repeat
end tell
return out
"""


class MailAgent:
    def execute(self, task: str) -> str:
        if platform.system() != "Darwin":
            return "Mail agent only works on macOS (uses Mail.app)."

        try:
            proc = subprocess.run(
                ["osascript", "-e", _APPLESCRIPT_UNREAD],
                capture_output=True,
                text=True,
                timeout=20,
            )
        except FileNotFoundError:
            return "osascript not found."
        except subprocess.TimeoutExpired:
            return "Mail query timed out."

        if proc.returncode != 0:
            err = proc.stderr.strip()
            if "not authorized" in err.lower() or "1743" in err:
                return (
                    "Need permission to read Mail. "
                    "Grant Automation access to Mail in System Settings."
                )
            log.error("osascript Mail failed: %s", err)
            return "Couldn't read your inbox."

        msgs = proc.stdout.strip()
        if not msgs:
            return "Inbox zero. Nothing unread."

        return haiku(
            system=(
                "Summarize unread emails for a voice assistant in 1–3 short sentences. "
                "Mention count, then notable senders or subjects. No emojis."
            ),
            user=msgs,
            max_tokens=180,
        )

    def raw_unread(self) -> str:
        """For the brief composer — raw lines, no Haiku pass."""
        if platform.system() != "Darwin":
            return ""
        try:
            proc = subprocess.run(
                ["osascript", "-e", _APPLESCRIPT_UNREAD],
                capture_output=True,
                text=True,
                timeout=20,
            )
            if proc.returncode != 0:
                return ""
            return proc.stdout.strip()
        except Exception:
            return ""


def build_mail_agent(config: "Config"):
    """Return whichever mail agent matches config.mail_backend."""
    backend = config.mail_backend
    if backend == "gmail":
        from .gmail import GmailAgent

        return GmailAgent(
            credentials_path=config.gmail_credentials_path,
            token_path=config.gmail_token_path,
        )
    # Default: macOS Mail.app via AppleScript.
    return MailAgent()
