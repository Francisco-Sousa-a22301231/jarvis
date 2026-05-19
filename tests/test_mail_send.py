"""Mail-send agent tests. Mocks the Haiku extractor and Gmail send."""
from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from jarvis.agents.mail_send import MailSendAgent


@pytest.fixture
def agent(tmp_path: Path):
    contacts = tmp_path / "contacts.toml"
    contacts.write_text(
        '[contacts]\npedro = "pedro@example.com"\n', encoding="utf-8"
    )
    return MailSendAgent(
        gmail_credentials_path=tmp_path / "creds.json",
        gmail_token_path=tmp_path / "token.json",
        contacts_path=contacts,
    )


def test_propose_resolves_known_nickname(agent: MailSendAgent):
    with patch(
        "jarvis.agents.mail_send.haiku",
        return_value='{"to_name":"Pedro","subject":"Running late","body":"I will be 10 min late."}',
    ):
        proposal = agent.propose("email Pedro that I'll be 10 minutes late")
    assert "pedro@example.com" in proposal
    assert "Running late" in proposal


def test_propose_unknown_nickname(agent: MailSendAgent):
    with patch(
        "jarvis.agents.mail_send.haiku",
        return_value='{"to_name":"Bob","subject":"hi","body":"hello"}',
    ):
        proposal = agent.propose("email Bob hi")
    assert "don't have an email" in proposal.lower()


def test_execute_uses_cache_from_propose(agent: MailSendAgent):
    task = "email Pedro running late"
    with patch(
        "jarvis.agents.mail_send.haiku",
        return_value='{"to_name":"Pedro","subject":"Late","body":"15m"}',
    ) as fake_haiku:
        agent.propose(task)
        assert fake_haiku.call_count == 1
        with patch.object(agent.gmail, "send", return_value="Sent.") as send:
            result = agent.execute(task)
    send.assert_called_once_with(to="pedro@example.com", subject="Late", body="15m")
    assert result == "Sent."


def test_execute_aborts_when_no_address(agent: MailSendAgent):
    with patch(
        "jarvis.agents.mail_send.haiku",
        return_value='{"to_name":"Stranger","subject":"hi","body":"hi"}',
    ):
        agent.propose("email Stranger hi")
        with patch.object(agent.gmail, "send") as send:
            result = agent.execute("email Stranger hi")
    send.assert_not_called()
    assert "no email" in result.lower() or "stranger" in result.lower()


def test_extract_handles_bad_json():
    # Direct call to the static extractor with mocked llm
    with patch("jarvis.agents.mail_send.haiku", return_value="garbage no json"):
        data = MailSendAgent._extract("email Pedro hi")
    assert data["body"] == "email Pedro hi"  # falls back to raw task
