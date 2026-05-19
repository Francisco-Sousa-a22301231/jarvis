"""QA spec generator tests. Mocks subprocess so no real git or claude calls."""
from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from jarvis.qa_spec import MIN_DIFF_LINES, generate_spec


def _proc(returncode: int, stdout: str = "", stderr: str = ""):
    return type("P", (), {"returncode": returncode, "stdout": stdout, "stderr": stderr})()


def test_skips_when_not_a_git_repo(tmp_path: Path):
    with patch("jarvis.qa_spec.shutil.which", return_value="/usr/bin/claude"):
        result = generate_spec(project_root=tmp_path)
    assert not result.success
    assert "not a git repo" in result.message


def test_skips_when_claude_missing(tmp_path: Path):
    (tmp_path / ".git").mkdir()
    with patch("jarvis.qa_spec.shutil.which", return_value=None):
        result = generate_spec(project_root=tmp_path)
    assert not result.success
    assert "PATH" in result.message


def test_skips_tiny_diff(tmp_path: Path):
    (tmp_path / ".git").mkdir()
    short_diff = "\n".join(["+small"] * (MIN_DIFF_LINES - 2))
    with patch("jarvis.qa_spec.shutil.which", return_value="/usr/bin/claude"), patch(
        "jarvis.qa_spec._run_git", return_value=short_diff
    ):
        result = generate_spec(project_root=tmp_path)
    assert not result.success
    assert "too small" in result.message


def test_writes_spec_on_success(tmp_path: Path):
    (tmp_path / ".git").mkdir()
    big_diff = "\n".join(["+ line %d" % i for i in range(30)])
    with patch("jarvis.qa_spec.shutil.which", return_value="/usr/bin/claude"), patch(
        "jarvis.qa_spec._run_git", return_value=big_diff
    ), patch("jarvis.qa_spec.subprocess.run") as run:
        run.return_value = _proc(
            0,
            stdout="URL: http://localhost:8000\nSteps:\n1. Click button.\nVerify: text changes.",
        )
        result = generate_spec(project_root=tmp_path)
    assert result.success
    assert result.spec_path is not None
    assert result.spec_path.exists()
    assert "URL:" in result.spec_path.read_text(encoding="utf-8")


def test_handles_claude_failure(tmp_path: Path):
    (tmp_path / ".git").mkdir()
    big_diff = "\n".join(["+line"] * 30)
    with patch("jarvis.qa_spec.shutil.which", return_value="/usr/bin/claude"), patch(
        "jarvis.qa_spec._run_git", return_value=big_diff
    ), patch("jarvis.qa_spec.subprocess.run") as run:
        run.return_value = _proc(1, stderr="auth expired")
        result = generate_spec(project_root=tmp_path)
    assert not result.success
    assert "auth expired" in result.message
