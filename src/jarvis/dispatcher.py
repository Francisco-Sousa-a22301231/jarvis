"""Dispatcher: take a Routed decision, run the right agent, return a spoken string.

Each agent has an `execute(task: str) -> str` method (the Agent protocol in
agents/base.py). Errors are caught here so the daemon never dies from a single
failed call — the user just hears a short apology and the loop continues.
"""
from __future__ import annotations

import logging
from typing import Callable

from .agents.base import Agent
from .router import Routed

log = logging.getLogger(__name__)


class Dispatcher:
    def __init__(self, agents: dict[str, Agent]):
        # skill_id -> Agent. Multiple skill_ids may map to the same agent
        # instance (e.g. trello_query and trello_create both → TrelloAgent).
        self.agents = agents

    def execute(self, routed: Routed) -> str:
        agent = self.agents.get(routed.skill)
        if agent is None:
            log.error("No agent registered for skill %r", routed.skill)
            return f"I don't have a handler for {routed.skill}."

        log.info("Dispatch: skill=%s task=%r", routed.skill, routed.task[:80])
        try:
            return agent.execute(routed.task)
        except Exception:
            log.exception("Agent %r raised", routed.skill)
            return "Something went wrong on that one."
