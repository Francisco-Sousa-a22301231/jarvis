"""LLM wrapper that uses Claude Code (and therefore your Max subscription).

Why subprocess instead of the `anthropic` SDK:
  The Anthropic API is a separate product from the Claude.ai / Max subscription.
  The SDK bills pay-as-you-go even if you're a Max subscriber. Routing every
  call through the `claude` CLI keeps all LLM usage on the Max plan.

Tradeoff: each spawn is ~1–2s of overhead vs ~400ms for a direct API call.
For Phase 2 voice commands that hit router + summarizer, that's ~2–3s extra
perceived latency. We mitigate later with a keyword fast-path that skips the
router for unambiguous phrases.
"""
from __future__ import annotations

import logging
import shutil
import subprocess

log = logging.getLogger(__name__)

DEFAULT_MODEL = "claude-haiku-4-5"
CLAUDE_BIN = "claude"

# Anything file/code/web-touching — deny by default so router/summarizer calls
# can't accidentally trigger an agentic loop. Pure text in, text out.
_DISALLOWED_TOOLS = (
    "Read,Write,Edit,Bash,Glob,Grep,Task,TodoWrite,WebFetch,WebSearch,"
    "NotebookEdit,Agent,SlashCommand"
)


def haiku(
    system: str,
    user: str,
    max_tokens: int = 300,  # advisory only — not enforceable via CLI
    cache: bool = True,     # ignored — Claude Code may cache internally
    model: str = DEFAULT_MODEL,
    timeout: int = 60,
) -> str:
    """One-shot LLM call via the `claude` CLI. Returns trimmed text.

    Args:
        system: behavior/persona instructions (concatenated with `user`).
        user:   the actual content to classify, summarize, or answer.
        model:  Claude model id. Defaults to Haiku 4.5 for cost/speed.
        timeout: seconds before we kill the spawn.

    Raises:
        RuntimeError: claude CLI missing, timed out, or returned non-zero.
    """
    if not shutil.which(CLAUDE_BIN):
        raise RuntimeError(
            f"`{CLAUDE_BIN}` not on PATH. Install Claude Code: "
            "https://docs.claude.com/en/docs/claude-code/quickstart"
        )

    prompt = (
        f"{system}\n\n"
        "--- User input ---\n"
        f"{user}\n"
        "--- End input ---\n\n"
        "Reply with the requested output only. Do NOT use any tools. "
        "Do NOT explain your reasoning."
    )

    cmd = [
        CLAUDE_BIN,
        "-p",
        "--model", model,
        "--output-format", "text",
        "--disallowedTools", _DISALLOWED_TOOLS,
    ]

    log.debug("claude -p model=%s prompt_len=%d", model, len(prompt))
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
        raise RuntimeError(f"LLM call timed out after {timeout}s")

    if proc.returncode != 0:
        log.error("claude -p exit=%d stderr=%r", proc.returncode, proc.stderr[:300])
        raise RuntimeError(
            f"claude CLI exited {proc.returncode}: {proc.stderr.strip()[:200] or '(no stderr)'}"
        )

    return proc.stdout.strip()
