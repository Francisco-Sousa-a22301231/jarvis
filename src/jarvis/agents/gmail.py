"""Gmail OAuth agent: read unread mail via the Gmail API.

For users who don't run macOS Mail.app. Setup is more work than the
AppleScript path:

  1. https://console.cloud.google.com/  →  new project (or reuse).
  2. Enable the Gmail API.
  3. APIs & Services → Credentials → Create OAuth client ID → Desktop app.
  4. Download credentials JSON → save as ~/.jarvis/gmail-credentials.json.
  5. First run pops a browser to authorize; token is cached at
     ~/.jarvis/gmail-token.json. Subsequent runs are silent.

Scopes: read-only. Sending is intentionally NOT in this agent yet — that
would be a destructive action and belongs behind the confirmation gate.
"""
from __future__ import annotations

import logging
from pathlib import Path

from ..llm import haiku

log = logging.getLogger(__name__)

SCOPES = [
    "https://www.googleapis.com/auth/gmail.readonly",
    "https://www.googleapis.com/auth/gmail.send",
]


class GmailAgent:
    def __init__(
        self,
        credentials_path: Path,
        token_path: Path,
        max_results: int = 8,
    ):
        self.credentials_path = credentials_path
        self.token_path = token_path
        self.max_results = max_results
        self._service = None

    def _service_or_error(self) -> tuple[object | None, str | None]:
        if self._service is not None:
            return self._service, None
        try:
            from google.auth.transport.requests import Request
            from google.oauth2.credentials import Credentials
            from google_auth_oauthlib.flow import InstalledAppFlow
            from googleapiclient.discovery import build
        except ImportError:
            return None, (
                "Gmail libraries missing. Install with `pip install -e .[gmail]`."
            )

        if not self.credentials_path.exists():
            return None, (
                f"Gmail credentials missing at {self.credentials_path}. "
                "See README — Phase 4 Gmail setup."
            )

        creds = None
        if self.token_path.exists():
            try:
                creds = Credentials.from_authorized_user_file(
                    str(self.token_path), SCOPES
                )
            except Exception as e:
                log.warning("Gmail token unreadable (%s); will reauth", e)

        if not creds or not creds.valid:
            if creds and creds.expired and creds.refresh_token:
                try:
                    creds.refresh(Request())
                except Exception as e:
                    log.warning("Token refresh failed (%s); falling back to flow", e)
                    creds = None
            if not creds:
                flow = InstalledAppFlow.from_client_secrets_file(
                    str(self.credentials_path), SCOPES
                )
                creds = flow.run_local_server(port=0)
            self.token_path.parent.mkdir(parents=True, exist_ok=True)
            self.token_path.write_text(creds.to_json(), encoding="utf-8")

        self._service = build("gmail", "v1", credentials=creds, cache_discovery=False)
        return self._service, None

    def _fetch_unread(self) -> list[str]:
        service, err = self._service_or_error()
        if err is not None:
            raise RuntimeError(err)
        resp = (
            service.users()
            .messages()
            .list(userId="me", labelIds=["UNREAD", "INBOX"], maxResults=self.max_results)
            .execute()
        )
        msg_ids = [m["id"] for m in resp.get("messages", [])]
        rows: list[str] = []
        for mid in msg_ids:
            msg = (
                service.users()
                .messages()
                .get(userId="me", id=mid, format="metadata",
                     metadataHeaders=["From", "Subject"])
                .execute()
            )
            headers = {h["name"]: h["value"] for h in msg.get("payload", {}).get("headers", [])}
            sender = headers.get("From", "?")
            subject = headers.get("Subject", "(no subject)")
            rows.append(f"{sender} | {subject}")
        return rows

    # ─── Agent protocol ─────────────────────────────────────────────────────

    def execute(self, task: str) -> str:
        try:
            rows = self._fetch_unread()
        except RuntimeError as e:
            return str(e)
        except Exception:
            log.exception("Gmail fetch failed")
            return "Couldn't reach Gmail."

        if not rows:
            return "Inbox zero. Nothing unread."

        return haiku(
            system=(
                "Summarize unread emails for a voice assistant in 1–3 short "
                "sentences. Mention count, then notable senders or subjects. "
                "No emojis."
            ),
            user="\n".join(rows),
            max_tokens=180,
        )

    def raw_unread(self) -> str:
        """For the brief composer — raw lines, no Haiku pass."""
        try:
            return "\n".join(self._fetch_unread())
        except Exception:
            return ""

    # ─── Outbound ──────────────────────────────────────────────────────────

    def send(self, to: str, subject: str, body: str) -> str:
        """Send a plain-text email via the authenticated Gmail account."""
        import base64
        from email.mime.text import MIMEText

        service, err = self._service_or_error()
        if err is not None:
            return err
        msg = MIMEText(body)
        msg["to"] = to
        msg["subject"] = subject
        raw = base64.urlsafe_b64encode(msg.as_bytes()).decode("ascii")
        try:
            service.users().messages().send(
                userId="me", body={"raw": raw}
            ).execute()
        except Exception as e:
            log.exception("Gmail send failed")
            return f"Couldn't send: {e}"
        return f"Sent to {to}."
