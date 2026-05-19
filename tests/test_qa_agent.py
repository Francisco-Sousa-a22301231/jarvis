"""QA agent tests. We don't actually drive a browser here — just verify the
agent's contract: spec-file handling, error messages, prompt construction."""
from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from jarvis.agents.qa import SPEC_FILENAME, QAAgent


def _agent(tmp_path: Path) -> QAAgent:
    mcp = tmp_path / "mcp.json"
    mcp.write_text('{"mcpServers": {}}')
    return QAAgent(project_root=tmp_path, mcp_config_path=mcp, timeout=5)


def test_missing_spec_returns_friendly_string(tmp_path: Path):
    agent = _agent(tmp_path)
    out = agent.execute(task="")
    assert SPEC_FILENAME in out
    assert "Claude Code" in out


def test_missing_mcp_config(tmp_path: Path):
    (tmp_path / SPEC_FILENAME).write_text("test")
    agent = QAAgent(
        project_root=tmp_path,
        mcp_config_path=tmp_path / "does-not-exist.json",
        timeout=5,
    )
    out = agent.execute(task="")
    assert "MCP config missing" in out


def test_prompt_includes_spec_and_rules():
    prompt = QAAgent._build_prompt("URL: http://x\n1. click button")
    assert "URL: http://x" in prompt
    assert "click button" in prompt
    assert "PASS" in prompt and "FAIL" in prompt
    assert "snapshot" in prompt.lower()


def test_pass_removes_spec(tmp_path: Path):
    spec = tmp_path / SPEC_FILENAME
    spec.write_text("anything")
    agent = _agent(tmp_path)
    with patch("jarvis.agents.qa.subprocess.run") as run, patch(
        "jarvis.agents.qa.shutil.which", return_value="/usr/bin/claude"
    ):
        run.return_value = type(
            "P", (), {"returncode": 0, "stdout": "PASS — all steps green", "stderr": ""}
        )()
        result = agent.execute(task="")
    assert result.startswith("PASS")
    assert not spec.exists(), "Spec should be deleted after a PASS run"


def test_fail_keeps_spec(tmp_path: Path):
    spec = tmp_path / SPEC_FILENAME
    spec.write_text("anything")
    agent = _agent(tmp_path)
    with patch("jarvis.agents.qa.subprocess.run") as run, patch(
        "jarvis.agents.qa.shutil.which", return_value="/usr/bin/claude"
    ):
        run.return_value = type(
            "P", (), {"returncode": 0, "stdout": "FAIL — step 3 timed out", "stderr": ""}
        )()
        result = agent.execute(task="")
    assert result.startswith("FAIL")
    assert spec.exists(), "Spec should be preserved after FAIL for iteration"
