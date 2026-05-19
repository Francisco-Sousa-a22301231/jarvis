"""Gmail OAuth agent: read unread mail + send via the Gmail API.

Cross-platform (works on Mac and Windows). Setup is the one-time Google
Cloud Console flow — see README → Google setup.

Auth is shared with the Google Calendar agent through google_auth.py, so
one credentials.json + one token.json covers both.
"""
from __future__ import annotations

import logging
from pathlib import Path

from ..google_auth import build_service
from ..llm import haiku

log = logging.getLogger(__name__)


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
            self._service = build_service(
                "gmail", "v1", self.credentials_path, self.token_path
            )
        except RuntimeError as e:
            return None, str(e)
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
