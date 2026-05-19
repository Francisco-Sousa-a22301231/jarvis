"""QA tester agent. Black-box live testing via Playwright MCP.

Design discipline — context efficiency by construction:
  - QA agent NEVER sees source code (by design)
  - Reads a tiny test spec written by the coder (Opus) at <project>/.jarvis-qa-spec.md
  - Drives a real browser through Playwright MCP — sees ARIA-tree snapshots, not
    pixel screenshots (<1KB per page typical)
  - Uses Haiku, not Opus — ~10-50× cheaper per call
  - Built-in Read/Write/Bash/Glob/Grep tools are explicitly disallowed so the
    agent literally cannot poke at the codebase

The spec file is the only contract between coder and QA. After a successful
run we delete the spec so the next session starts clean.
"""
from __future__ import annotations

import logging
import shutil
import subprocess
from pathlib import Path

log = logging.getLogger(__name__)

SPEC_FILENAME = ".jarvis-qa-spec.md"
DEFAULT_TIMEOUT = 300  # 5 min — generous for a full multi-step browser run

# Built-in Playwright MCP tool names (microsoft/playwright-mcp).
# If you swap in a different MCP server, update this list.
_PLAYWRIGHT_TOOLS = ",".join(
    [
        "mcp__playwright__browser_navigate",
        "mcp__playwright__browser_snapshot",
        "mcp__playwright__browser_click",
        "mcp__playwright__browser_type",
        "mcp__playwright__browser_press_key",
        "mcp__playwright__browser_select_option",
        "mcp__playwright__browser_wait_for",
        "mcp__playwright__browser_console_messages",
        "mcp__playwright__browser_network_requests",
        "mcp__playwright__browser_take_screenshot",
        "mcp__playwright__browser_close",
    ]
)

# Everything else — disallow. The QA agent must not touch the codebase.
_DISALLOWED_TOOLS = (
    "Read,Write,Edit,Bash,Glob,Grep,Task,TodoWrite,WebFetch,WebSearch,"
    "NotebookEdit,Agent,SlashCommand"
)


class QAAgent:
    def __init__(
        self,
        project_root: Path,
        mcp_config_path: Path,
        claude_bin: str = "claude",
        model: str = "claude-haiku-4-5",
        timeout: int = DEFAULT_TIMEOUT,
    ):
        self.project_root = project_root
        self.mcp_config_path = mcp_config_path
        self.claude_bin = claude_bin
        self.model = model
        self.timeout = timeout

    def execute(self, task: str) -> str:
        if not shutil.which(self.claude_bin):
            return f"`{self.claude_bin}` not on PATH. Install Claude Code first."

        spec_path = self.project_root / SPEC_FILENAME
        if not spec_path.exists():
            return (
                f"No QA spec at {spec_path}. Ask Claude Code to write a "
                f"{SPEC_FILENAME} with URL + steps before running QA."
            )
        if not self.mcp_config_path.exists():
            return (
                f"MCP config missing at {self.mcp_config_path}. "
                "See README — Phase 3 QA setup."
            )

        spec = spec_path.read_text(encoding="utf-8")
        prompt = self._build_prompt(spec)

        cmd = [
            self.claude_bin,
            "-p",
            "--model", self.model,
            "--mcp-config", str(self.mcp_config_path),
            "--allowedTools", _PLAYWRIGHT_TOOLS,
            "--disallowedTools", _DISALLOWED_TOOLS,
            "--output-format", "text",
        ]
        log.info("QA run: project=%s spec=%s", self.project_root, spec_path.name)
        try:
            proc = subprocess.run(
                cmd,
                input=prompt,
                capture_output=True,
                text=True,
                timeout=self.timeout,
                check=False,
            )
        except subprocess.TimeoutExpired:
            return f"QA timed out after {self.timeout}s."

        if proc.returncode != 0:
            log.error("QA exit=%d stderr=%r", proc.returncode, proc.stderr[:400])
            return f"QA failed to run: {proc.stderr.strip()[:200] or '(no stderr)'}"

        result = proc.stdout.strip() or "QA finished with no output."
        # On success, remove the spec so the next session starts clean.
        # We keep the spec on failure so you can iterate.
        if result.upper().startswith("PASS"):
            try:
                spec_path.unlink()
            except OSError:
                pass
        return result

    @staticmethod
    def _build_prompt(spec: str) -> str:
        return (
            "You are a QA tester. Execute the test spec below against the running "
            "app, using ONLY the Playwright MCP tools.\n\n"
            "Rules:\n"
            " - Use browser_snapshot (ARIA tree) to verify state — NOT screenshots "
            "unless explicitly asked.\n"
            " - You may NOT read or write source code. The spec is the only contract.\n"
            " - Always navigate first, then execute each numbered step in order.\n"
            " - If a step fails or the app behaves differently than the spec implies, "
            "capture the relevant snapshot and stop — don't keep going.\n"
            " - End with EXACTLY one line: 'PASS — <one-sentence summary>' or "
            "'FAIL — <step that failed + what went wrong>'.\n\n"
            "--- TEST SPEC ---\n"
            f"{spec}\n"
            "--- END SPEC ---"
        )
