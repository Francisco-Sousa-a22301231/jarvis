"""Anthropic client wrapper with prompt caching helper.

Single shared client. Lazy-initialized. Reads ANTHROPIC_API_KEY from env.
All Haiku calls use prompt caching on the system block to amortize router/agent prompts.
"""
from __future__ import annotations

import logging
import os
from typing import Any

from anthropic import Anthropic

log = logging.getLogger(__name__)

DEFAULT_MODEL = "claude-haiku-4-5"

_client: Anthropic | None = None


def get_client() -> Anthropic:
    global _client
    if _client is None:
        api_key = os.getenv("ANTHROPIC_API_KEY")
        if not api_key:
            raise RuntimeError(
                "ANTHROPIC_API_KEY not set. Required for router, summarizer, and agents."
            )
        _client = Anthropic(api_key=api_key)
    return _client


def haiku(
    system: str,
    user: str,
    max_tokens: int = 300,
    cache: bool = True,
    model: str = DEFAULT_MODEL,
) -> str:
    """One-shot Haiku call. Returns the trimmed text response.

    If `cache=True`, the system block is marked cache_control:ephemeral so
    repeat calls with the same system prompt hit the cache (~10x cheaper).
    """
    client = get_client()
    if cache:
        system_block: Any = [
            {"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}
        ]
    else:
        system_block = system

    resp = client.messages.create(
        model=model,
        max_tokens=max_tokens,
        system=system_block,
        messages=[{"role": "user", "content": user}],
    )
    log.debug(
        "haiku call: in=%d out=%d cache_read=%d cache_create=%d",
        resp.usage.input_tokens,
        resp.usage.output_tokens,
        getattr(resp.usage, "cache_read_input_tokens", 0) or 0,
        getattr(resp.usage, "cache_creation_input_tokens", 0) or 0,
    )
    return resp.content[0].text.strip()
