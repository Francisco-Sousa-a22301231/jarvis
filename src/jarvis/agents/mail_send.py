"""Send-mail agent: voice → email via Gmail OAuth + confirmation gate.

Flow:
  1. Loop checks `requires_confirm` on the skill and calls agent.propose(task).
  2. propose() asks Haiku to extract {to_name, subject, body} from the
     transcript and resolves the nickname against contacts.toml. Cached.
  3. Loop speaks the proposal and waits for "yes".
  4. On confirmation, execute() pulls the cached extraction and sends.

Why caching: extraction is a Haiku call. We don't want to run it twice
(once for proposal, once for execute) just to save the user 1 second.
"""
from __future__ import annotations

import json
import logging
import re
from pathlib import Path

from .. import contacts as contacts_mod
from ..llm import haiku
from .gmail import GmailAgent

log = logging.getLogger(__name__)


_EXTRACT_SYSTEM = (
    "Extract a single email from the user's request. Reply with ONLY a JSON "
    "object on one line:\n"
    '{"to_name": "<person name or address>", "subject": "<short subject>", '
    '"body": "<short, complete body in the same language as the user>"}'
    "\n\nRules:\n"
    " - to_name is whichever name the user said (could be a nickname or an "
    "actual email).\n"
    " - subject is 3-7 words, no punctuation at the end.\n"
    " - body is 1-3 sentences, complete and ready to send. No greeting/signoff "
    "unless the user asked for one. Match the user's language."
)

_JSON_RE = re.compile(r"\{.*\}", re.DOTALL)


class MailSendAgent:
    def __init__(
        self,
        gmail_credentials_path: Path,
        gmail_token_path: Path,
        contacts_path: Path,
    ):
        self.gmail = GmailAgent(
            credentials_path=gmail_credentials_path,
            token_path=gmail_token_path,
        )
        self.contacts_path = contacts_path
        self._cache: dict | None = None  # last extraction

    # ─── Used by loop before the confirmation gate ─────────────────────────

    def propose(self, task: str) -> str:
        extracted = self._extract(task)
        contacts = contacts_mod.load(self.contacts_path)
        addr = contacts_mod.resolve(extracted["to_name"], contacts)

        self._cache = {
            "task": task,
            "to_name": extracted["to_name"],
            "to_addr": addr,
            "subject": extracted["subject"],
            "body": extracted["body"],
        }

        if addr is None:
            return (
                f"I don't have an email for {extracted['to_name']!r}. "
                "Add them to contacts.toml first."
            )
        return (
            f"I'll email {extracted['to_name']} at {addr}: "
            f"subject '{extracted['subject']}', body '{extracted['body']}'."
        )

    # ─── Agent protocol ─────────────────────────────────────────────────────

    def execute(self, task: str) -> str:
        cached = self._cache if (self._cache and self._cache.get("task") == task) else None
        if cached is None:
            # Confirmation gate wasn't used (e.g. CLI). Extract now.
            cached = {**self._extract(task)}
            contacts = contacts_mod.load(self.contacts_path)
            cached["to_addr"] = contacts_mod.resolve(cached["to_name"], contacts)
        self._cache = None

        if not cached.get("to_addr"):
            return f"No email address for {cached['to_name']!r}. Aborting."

        return self.gmail.send(
            to=cached["to_addr"],
            subject=cached["subject"],
            body=cached["body"],
        )

    # ─── internals ─────────────────────────────────────────────────────────

    @staticmethod
    def _extract(task: str) -> dict[str, str]:
        raw = haiku(system=_EXTRACT_SYSTEM, user=task, max_tokens=200, cache=True)
        match = _JSON_RE.search(raw)
        if not match:
            log.warning("mail_send extract: no JSON in %r", raw)
            return {"to_name": "", "subject": "", "body": task}
        try:
            data = json.loads(match.group(0))
        except json.JSONDecodeError:
            log.warning("mail_send extract: bad JSON %r", raw)
            return {"to_name": "", "subject": "", "body": task}
        return {
            "to_name": str(data.get("to_name", "")).strip(),
            "subject": str(data.get("subject", "")).strip() or "(no subject)",
            "body": str(data.get("body", "")).strip() or task,
        }
