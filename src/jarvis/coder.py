"""Spawn Claude Code to execute a coding task.

The Coder optionally renders its task through a versioned prompt template
(see prompt_registry.py). The selected template_id is attached to the
result so the loop can score it later (e.g. when QA passes or fails).
"""
from __future__ import annotations

import logging
import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

log = logging.getLogger(__name__)

if TYPE_CHECKING:
    from .prompt_registry import PromptRegistry


@dataclass
class CoderResult:
    success: bool
    output: str
    error: str = ""
    template_id: str | None = None  # which prompt template was used
    task: str = ""                   # original task (for outcome recording)

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
        prompt_registry: "PromptRegistry | None" = None,
    ):
        self.project_root = project_root
        self.claude_bin = claude_bin
        self.dangerously_skip = dangerously_skip_permissions
        self.timeout = timeout_seconds
        self.prompt_registry = prompt_registry

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
        # Render through the prompt registry if available; otherwise pass the
        # raw task through (Phase 1 / pre-Phase-7 behaviour).
        template_id: str | None = None
        rendered = task
        if self.prompt_registry is not None:
            template_id, rendered = self.prompt_registry.render("code", task)

        cmd = [self.claude_bin, "-p", rendered, "--output-format", "text"]
        if self.dangerously_skip:
            cmd.append("--dangerously-skip-permissions")

        log.info(
            "Running Claude Code in %s [template=%s]: %s",
            self.project_root,
            template_id or "(raw)",
            task[:80],
        )
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
            return CoderResult(
                False, "", f"Timed out after {self.timeout}s",
                template_id=template_id, task=task,
            )
        except FileNotFoundError as e:
            return CoderResult(
                False, "", str(e), template_id=template_id, task=task,
            )

        if proc.returncode != 0:
            return CoderResult(
                False, proc.stdout,
                proc.stderr or f"exit {proc.returncode}",
                template_id=template_id, task=task,
            )
        return CoderResult(True, proc.stdout, template_id=template_id, task=task)
