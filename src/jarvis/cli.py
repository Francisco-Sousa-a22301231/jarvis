"""CLI subcommands: `jarvis brief`, `jarvis route <text>`.

The main daemon entrypoint lives in __main__.py; this module holds the
one-shot subcommands that share its config/agent wiring.
"""
from __future__ import annotations

import logging
import sys

from .agents.brief import BriefAgent
from .agents.calendar import CalendarAgent
from .agents.mail import build_mail_agent
from .agents.qa import QAAgent
from .agents.trello import TrelloAgent
from .config import Config
from .router import route

log = logging.getLogger(__name__)


def _build_brief_agent(config: Config) -> BriefAgent:
    try:
        trello: TrelloAgent | None = TrelloAgent()
    except RuntimeError as e:
        log.warning("Trello disabled: %s", e)
        trello = None
    return BriefAgent(
        trello=trello,
        calendar=CalendarAgent(),
        mail=build_mail_agent(config),
    )


def cmd_brief(config: Config) -> int:
    """Compose today's brief and print to stdout. Suitable for launchd."""
    brief = _build_brief_agent(config)
    print(brief.execute(task=""))
    return 0


def cmd_route(_config: Config, text: str) -> int:
    """Run the router on `text` without executing. Prints the routing decision."""
    decision = route(text)
    print(f"skill: {decision.skill}")
    print(f"task:  {decision.task}")
    return 0


def cmd_daemon(config: Config) -> int:
    """The main always-on voice loop."""
    from .loop import run

    try:
        run(config)
    except KeyboardInterrupt:
        print("\nShutting down.", file=sys.stderr)
        return 0
    except Exception:
        log.exception("Fatal error in daemon loop")
        return 1
    return 0


def cmd_qa(config: Config) -> int:
    """Run the QA agent against the spec in the configured project dir."""
    agent = QAAgent(
        project_root=config.default_project,
        mcp_config_path=config.mcp_config_path,
        claude_bin=config.claude_bin,
    )
    result = agent.execute(task="")
    print(result)
    return 0 if result.upper().startswith("PASS") else 1


def cmd_spec(config: Config) -> int:
    """Generate a QA spec from the project's uncommitted diff."""
    from .qa_spec import generate_spec

    result = generate_spec(
        project_root=config.default_project,
        claude_bin=config.claude_bin,
    )
    print(result.message)
    return 0 if result.success else 1
