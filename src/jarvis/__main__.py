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

from .cli import cmd_brief, cmd_daemon, cmd_qa, cmd_route
from .config import Config


def main() -> int:
    parser = argparse.ArgumentParser(prog="jarvis")
    sub = parser.add_subparsers(dest="cmd")

    sub.add_parser("daemon", help="Run the voice daemon (default)")
    sub.add_parser("brief", help="Compose and print today's brief")
    sub.add_parser("qa", help="Run the QA agent on the pending spec")

    route_p = sub.add_parser("route", help="Debug: route a piece of text")
    route_p.add_argument("text", help="Text to classify")

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
    if cmd == "brief":
        return cmd_brief(config)
    if cmd == "qa":
        return cmd_qa(config)
    if cmd == "route":
        return cmd_route(config, args.text)

    parser.print_help()
    return 1


if __name__ == "__main__":
    sys.exit(main())
