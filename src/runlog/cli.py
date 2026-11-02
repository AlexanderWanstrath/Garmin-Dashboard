"""Command line entry point: runlog <command>."""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence

from runlog import __version__
from runlog.config import DEFAULT_CONFIG_PATH

# Command name -> (help text, roadmap stage that implements it).
COMMANDS = {
    "sync": ("Fetch new activities and health data from Garmin into the local database", "1b"),
    "log": ("Record manual entries such as tendon pain, RPE and fueling", "1d"),
    "build": ("Generate the dashboard HTML from the local database", "1e"),
    "demo": ("Generate a dashboard from synthetic data", "1f"),
    "mcp": ("Start the read-only MCP server for Claude Code", "1g"),
}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="runlog", description="Personal running analytics from Garmin data.")
    parser.add_argument("--version", action="version", version=f"runlog {__version__}")
    parser.add_argument(
        "--config",
        default=str(DEFAULT_CONFIG_PATH),
        help=f"path to the config file (default: {DEFAULT_CONFIG_PATH})",
    )
    subparsers = parser.add_subparsers(dest="command", metavar="<command>")
    for name, (help_text, _stage) in COMMANDS.items():
        subparsers.add_parser(name, help=help_text, description=help_text)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.command is None:
        parser.print_help()
        return 0
    stage = COMMANDS[args.command][1]
    print(f"runlog {args.command}: not implemented yet (roadmap stage {stage})", file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main())
