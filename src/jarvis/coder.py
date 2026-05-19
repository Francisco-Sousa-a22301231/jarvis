"""Spawn Claude Code to execute a coding task.

Phase 1: invokes the `claude` CLI in print mode (`-p`) as a subprocess.
Future: swap for the Claude Agent SDK for richer streaming.
"""
from __future__ import annotations

import logging
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

log = logging.getLogger(__name__)


@dataclass
class CoderResult:
    success: bool
    output: str
    error: str = ""

    @property
    def short(self) -> str:
        """First non-empty paragraph of the output, capped at 200 chars."""
        if not self.success:
            return f"Claude Code failed: {self.error[:160]}"
        text = self.output.strip()
        if not text:
            return "Done."
        # Take first paragraph
        first = text.split("\n\n")[0].replace("\n", " ").strip()
        if len(first) <= 200:
            return first
        cut = first[:200]
        if "." in cut:
            return cut[: cut.rfind(".") + 1]
        return cut + "..."


class Coder:
    def __init__(
        self,
        project_root: Path,
        claude_bin: str = "claude",
        dangerously_skip_permissions: bool = False,
        timeout_seconds: int = 600,
    ):
        self.project_root = project_root
        self.claude_bin = claude_bin
        self.dangerously_skip = dangerously_skip_permissions
        self.timeout = timeout_seconds

    def check(self) -> None:
        """Verify Claude Code is installed."""
        if not shutil.which(self.claude_bin):
            raise FileNotFoundError(
                f"`{self.claude_bin}` not on PATH. Install Claude Code: "
                f"https://docs.claude.com/en/docs/claude-code/quickstart"
            )
        if not self.project_root.exists():
            raise FileNotFoundError(f"Project root {self.project_root} does not exist")

    def execute(self, task: str) -> CoderResult:
        cmd = [self.claude_bin, "-p", task, "--output-format", "text"]
        if self.dangerously_skip:
            cmd.append("--dangerously-skip-permissions")

        log.info("Running Claude Code in %s: %s", self.project_root, task[:80])
        try:
            proc = subprocess.run(
                cmd,
                cwd=self.project_root,
                capture_output=True,
                text=True,
                timeout=self.timeout,
                check=False,
            )
        except subprocess.TimeoutExpired:
            return CoderResult(False, "", f"Timed out after {self.timeout}s")
        except FileNotFoundError as e:
            return CoderResult(False, "", str(e))

        if proc.returncode != 0:
            return CoderResult(False, proc.stdout, proc.stderr or f"exit {proc.returncode}")
        return CoderResult(True, proc.stdout)
