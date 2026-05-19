"""Entrypoint: `python -m jarvis [subcommand]`.

Subcommands:
  (none) | daemon   Run the always-on voice loop (default)
  brief             Compose today's brief and print it (for launchd)
  route <text>      Debug: show how the router would classify <text>
"""
from __future__ import annotations

import argparse
import logging
import sys

from .cli import (
    cmd_brief,
    cmd_daemon,
    cmd_listen,
    cmd_prompts,
    cmd_qa,
    cmd_route,
    cmd_serve,
    cmd_spec,
    cmd_watch,
)
from .config import Config


def main() -> int:
    parser = argparse.ArgumentParser(prog="jarvis")
    sub = parser.add_subparsers(dest="cmd")

    sub.add_parser("daemon", help="Run the voice daemon (default; needs Picovoice key)")
    listen_p = sub.add_parser(
        "listen",
        help="Push-to-talk: press Enter, speak, get a response (no wake word needed)",
    )
    listen_p.add_argument(
        "--loop", action="store_true",
        help="Keep listening after each turn instead of exiting",
    )
    sub.add_parser("brief", help="Compose and print today's brief")
    sub.add_parser("qa", help="Run the QA agent on the pending spec")
    sub.add_parser("spec", help="Generate a QA spec from the project's uncommitted diff")
    sub.add_parser(
        "watch",
        help="One-shot watcher: VIP mail + imminent calendar + Trello list moves",
    )
    sub.add_parser(
        "serve",
        help="Run the HTTP server for remote commands (phone / Shortcuts)",
    )

    route_p = sub.add_parser("route", help="Debug: route a piece of text")
    route_p.add_argument("text", help="Text to classify")

    prompts_p = sub.add_parser(
        "prompts",
        help="Inspect / evolve / feedback the Coder prompt registry",
    )
    prompts_sub = prompts_p.add_subparsers(dest="prompts_action")
    prompts_sub.add_parser("list", help="List all templates")
    prompts_sub.add_parser("stats", help="Per-template win rates")
    prompts_sub.add_parser("evolve", help="Propose an improved version of the worst template")
    fb = prompts_sub.add_parser("feedback", help="Manually record success/failure for a template")
    fb.add_argument("template_id")
    fb.add_argument("outcome", choices=["success", "failure", "unknown"])
    fb.add_argument("--task", default="", help="Optional task description for the record")
    for verb in ("activate", "deactivate"):
        p = prompts_sub.add_parser(verb, help=f"{verb.title()} a template (toggles A/B inclusion)")
        p.add_argument("template_id")

    args = parser.parse_args()
    cmd = args.cmd or "daemon"

    try:
        config = Config.load()
    except (FileNotFoundError, ValueError) as e:
        print(f"Config error: {e}", file=sys.stderr)
        return 1

    logging.basicConfig(
        level=getattr(logging, config.log_level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    if cmd == "daemon":
        return cmd_daemon(config)
    if cmd == "listen":
        return cmd_listen(config, loop_mode=bool(getattr(args, "loop", False)))
    if cmd == "brief":
        return cmd_brief(config)
    if cmd == "qa":
        return cmd_qa(config)
    if cmd == "spec":
        return cmd_spec(config)
    if cmd == "watch":
        return cmd_watch(config)
    if cmd == "serve":
        return cmd_serve(config)
    if cmd == "route":
        return cmd_route(config, args.text)
    if cmd == "prompts":
        if not args.prompts_action:
            prompts_p.print_help()
            return 1
        return cmd_prompts(config, args.prompts_action, args)

    parser.print_help()
    return 1


if __name__ == "__main__":
    sys.exit(main())
