"""CLI subcommands: `jarvis brief`, `jarvis route <text>`.

The main daemon entrypoint lives in __main__.py; this module holds the
one-shot subcommands that share its config/agent wiring.
"""
from __future__ import annotations

import logging
import sys

from .agents.brief import BriefAgent
from .agents.calendar import build_calendar_agent
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
        calendar=build_calendar_agent(config),
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


def cmd_watch(config: Config) -> int:
    """One-shot scan: VIP mail + imminent calendar + Trello list moves.

    Posts macOS notifications. Designed for launchd to run every few minutes.
    """
    from .watcher import run_all

    run = run_all(
        google_credentials_path=config.google_credentials_path,
        google_token_path=config.google_token_path,
        vip_senders=config.watcher_vip_senders,
        calendar_backend=config.calendar_backend,
        calendar_lead_minutes=config.watcher_calendar_lead_minutes,
        trello_watch_list=config.watcher_trello_list,
    )

    def line(name: str, r) -> str:
        if r.skipped_reason:
            return f"  {name:<8s} skipped — {r.skipped_reason}"
        return f"  {name:<8s} checked={r.checked} notified={r.notified}"

    print("Watcher run:")
    print(line("mail", run.mail))
    print(line("calendar", run.calendar))
    print(line("trello", run.trello))
    print(f"Total notifications: {run.total_notified}")
    return 0


def cmd_serve(config: Config) -> int:
    """Run the HTTP server for remote commands (phone-as-remote / shortcuts)."""
    from .server import serve

    return serve(config)


def cmd_prompts(config: Config, action: str, args) -> int:
    """Inspect, evolve, and feedback on the prompt registry."""
    from .prompt_evolution import evolve
    from .prompt_registry import PromptRegistry

    registry = PromptRegistry()

    if action == "list":
        for skill in sorted({t.skill for t in registry.templates_for("code", active_only=False) + []} | {"code"}):
            print(f"[skill: {skill}]")
            for t in registry.templates_for(skill, active_only=False):
                flag = "✓" if t.active else "·"
                print(f"  {flag} {t.id}  (parent={t.parent_id or '—'})")
                first_line = t.template.splitlines()[0][:80] if t.template else ""
                print(f"      {first_line}")
        return 0

    if action == "stats":
        rows = registry.stats()
        if not rows:
            print("No outcomes recorded yet. Run some code dispatches then `jarvis qa` to score them.")
            return 0
        print(f"{'template':<25s} {'trials':>7s} {'wins':>6s} {'losses':>7s} {'unknown':>8s} {'win%':>6s}")
        for s in sorted(rows, key=lambda r: r.template_id):
            wr = f"{s.win_rate * 100:.0f}%" if (s.successes + s.failures) else "—"
            print(
                f"{s.template_id:<25s} {s.trials:>7d} {s.successes:>6d} "
                f"{s.failures:>7d} {s.unknown:>8d} {wr:>6s}"
            )
        return 0

    if action == "evolve":
        result = evolve(registry, skill="code")
        print(result.message)
        return 0 if result.success else 1

    if action == "feedback":
        template_id = args.template_id
        outcome = args.outcome
        if registry.get(template_id) is None:
            print(f"Unknown template: {template_id}")
            return 1
        registry.record_outcome(template_id, args.task or "(manual)", outcome, "manual feedback")
        print(f"Recorded {outcome} for {template_id}.")
        return 0

    if action == "activate" or action == "deactivate":
        new_state = action == "activate"
        ok = registry.set_active(args.template_id, new_state)
        if not ok:
            print(f"Unknown template: {args.template_id}")
            return 1
        print(f"{args.template_id} → active={new_state}")
        return 0

    print(f"Unknown prompts action: {action}")
    return 1
