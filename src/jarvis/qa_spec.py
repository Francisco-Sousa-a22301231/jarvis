"""Generate a `.jarvis-qa-spec.md` from the project's uncommitted diff.

Workflow this enables:
  1. Claude Code finishes a feature in <project>. Diff is unstaged.
  2. `jarvis spec`  (or a Claude Code Stop hook running `jarvis spec`).
  3. `jarvis qa`  — the QA agent runs the spec end-to-end.

The spec generator uses a bigger model (Sonnet by default) since it needs to
reason about behavior changes, not just classify. Cost stays modest because
we cap the diff size and skip when there's nothing meaningful to test.
"""
from __future__ import annotations

import logging
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

log = logging.getLogger(__name__)

SPEC_FILENAME = ".jarvis-qa-spec.md"
DEFAULT_MODEL = "claude-sonnet-4-6"
MIN_DIFF_LINES = 8       # below this, skip — probably a typo or comment
MAX_DIFF_CHARS = 30_000  # cap so we don't ship a huge diff to Claude


_PROMPT_SYSTEM = """You write behavior-focused QA test specs.

Given a git diff, output a Markdown QA spec with:
  - "URL:" line (best guess for the affected route; localhost is fine)
  - "Steps:" numbered list of user actions
  - "Verify:" expected observable state after each step
  - "Failure modes:" 2-3 things that could subtly break

Rules:
  - Behaviour only. No internal implementation details. No code.
  - Plain markdown. No triple-backtick fences.
  - 12 lines or fewer total."""


@dataclass
class SpecResult:
    success: bool
    spec_path: Path | None
    message: str


def _run_git(args: list[str], cwd: Path) -> str:
    proc = subprocess.run(
        ["git", *args],
        cwd=cwd,
        capture_output=True,
        text=True,
        check=False,
        timeout=30,
    )
    if proc.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)} failed: {proc.stderr.strip()}")
    return proc.stdout


def generate_spec(
    project_root: Path,
    claude_bin: str = "claude",
    model: str = DEFAULT_MODEL,
    timeout: int = 120,
) -> SpecResult:
    if not shutil.which(claude_bin):
        return SpecResult(False, None, f"{claude_bin} not on PATH.")

    if not (project_root / ".git").exists():
        return SpecResult(False, None, f"{project_root} is not a git repo.")

    try:
        diff = _run_git(["diff", "--unified=3", "HEAD"], project_root)
    except RuntimeError as e:
        return SpecResult(False, None, str(e))

    if diff.count("\n") < MIN_DIFF_LINES:
        return SpecResult(
            False, None, f"Diff has only {diff.count(chr(10))} lines — too small to spec."
        )

    if len(diff) > MAX_DIFF_CHARS:
        diff = diff[:MAX_DIFF_CHARS] + "\n(...diff truncated)"

    spec_path = project_root / SPEC_FILENAME
    prompt = (
        f"{_PROMPT_SYSTEM}\n\n"
        f"--- DIFF ---\n{diff}\n--- END DIFF ---\n\n"
        "Output ONLY the markdown spec."
    )

    cmd = [
        claude_bin,
        "-p",
        "--model", model,
        "--output-format", "text",
        "--disallowedTools",
        "Read,Write,Edit,Bash,Glob,Grep,Task,TodoWrite,WebFetch,WebSearch,NotebookEdit,Agent,SlashCommand",
    ]
    try:
        proc = subprocess.run(
            cmd,
            input=prompt,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except subprocess.TimeoutExpired:
        return SpecResult(False, None, f"Spec generation timed out after {timeout}s.")

    if proc.returncode != 0:
        return SpecResult(
            False, None, f"claude -p failed: {proc.stderr.strip()[:200] or 'unknown error'}"
        )

    spec = proc.stdout.strip()
    if not spec:
        return SpecResult(False, None, "Spec generator returned no output.")

    spec_path.write_text(spec + "\n", encoding="utf-8")
    return SpecResult(True, spec_path, f"Wrote {spec_path}")
