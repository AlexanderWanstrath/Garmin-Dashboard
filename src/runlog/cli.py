"""Command line entry point: runlog <command>."""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from pathlib import Path

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


def cmd_sync(config_path: str) -> int:
    from runlog import config, db
    from runlog.sources.garmin_api import AuthError, GarminSource
    from runlog.sync import run_sync

    try:
        cfg = config.load_config(config_path)
    except config.ConfigError as exc:
        if Path(config_path).exists():
            print(f"Error: {exc}", file=sys.stderr)
            return 1
        print(f"Note: {config_path} not found, using defaults.", file=sys.stderr)
        cfg = {}
    try:
        start_date = config.sync_start_date(cfg)
    except config.ConfigError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    data_dir = config.data_dir(cfg)
    conn = db.connect(data_dir / "runlog.db")
    try:
        with GarminSource.open() as source:
            result = run_sync(conn, source, data_dir, start_date=start_date)
    except AuthError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    finally:
        conn.close()

    print(f"\nNew activities: {result.new_activities} (already stored: {result.known_activities})")
    if result.health_range:
        start, end = result.health_range
        print(f"Health data: {result.health_days} days ({start} to {end})")
    for warning in result.warnings:
        print(f"Warning: {warning}", file=sys.stderr)
    print(f"Database: {data_dir / 'runlog.db'}")
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.command is None:
        parser.print_help()
        return 0
    if args.command == "sync":
        return cmd_sync(args.config)
    stage = COMMANDS[args.command][1]
    print(f"runlog {args.command}: not implemented yet (roadmap stage {stage})", file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main())
