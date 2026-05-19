"""Memory-query agent tests."""
from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from jarvis.agents.memory_query import MemoryQueryAgent
from jarvis.memory import Memory


def test_empty_memory_returns_friendly_message(tmp_path: Path):
    agent = MemoryQueryAgent(memory=Memory(path=tmp_path / "recent.md"))
    out = agent.execute(task="what did I ask")
    assert "recent memory" in out.lower() or "nothing" in out.lower()


def test_summarizes_recent_via_haiku(tmp_path: Path):
    mem = Memory(path=tmp_path / "recent.md")
    mem.append("morning brief", "brief", "3 meetings today")
    mem.append("add a card to call pedro", "trello_create", "Added")
    agent = MemoryQueryAgent(memory=mem)
    with patch(
        "jarvis.agents.memory_query.haiku",
        return_value="You asked for a brief, then created a Trello card.",
    ) as fake:
        out = agent.execute(task="what did I ask earlier")
    assert "Trello" in out
    fake.assert_called_once()
    # Make sure Haiku saw both entries in the user block
    user_block = fake.call_args.kwargs.get("user") or fake.call_args.args[1]
    assert "morning brief" in user_block
    assert "pedro" in user_block.lower()
