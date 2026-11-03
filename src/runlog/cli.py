"""Command line entry point: runlog <command>."""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from datetime import date
from pathlib import Path
from typing import Any

from runlog import __version__
from runlog.config import DEFAULT_CONFIG_PATH

# Command name -> (help text, roadmap stage that implements it).
COMMANDS = {
    "sync": ("Fetch new activities and health data from Garmin into the local database", "1b"),
    "log": ("Record the morning check (patellar tendon, legs, hip) or fueling of a run", "1d"),
    "check": ("Show the morning check, warnings and the comparison with the training plan", "1d"),
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
    sub = {
        name: subparsers.add_parser(name, help=help_text, description=help_text)
        for name, (help_text, _stage) in COMMANDS.items()
    }

    log = sub["log"]
    log.add_argument("--date", type=date.fromisoformat, default=None, help="YYYY-MM-DD (default: today)")
    log.add_argument("--tendon", type=int, help="patellar tendon pain 0-10 (stairs and 10 single-leg squats)")
    log.add_argument("--startup-pain", action="store_true", help="pain when starting to move")
    log.add_argument("--legs", help="fresh, heavy or very-heavy (also: locker, schwer, sehr-schwer)")
    log.add_argument("--hip", action="store_true", help="hip pain")
    log.add_argument("--fuel", type=float, metavar="GRAMS", help="carbohydrates taken during a run")
    log.add_argument("--activity", help="run the fueling belongs to: 'last' (default) or an activity id")
    log.add_argument("--note", help="free text")

    sub["sync"].add_argument(
        "--reparse", action="store_true", help="re-read the stored FIT files instead of calling Garmin"
    )
    sub["check"].add_argument("--date", type=date.fromisoformat, default=None, help="YYYY-MM-DD (default: today)")

    build = sub["build"]
    build.add_argument("--output", default="output/dashboard.html", help="HTML file to write")
    build.add_argument("--date", type=date.fromisoformat, default=None, help="build as of YYYY-MM-DD (default: today)")
    build.add_argument("--open", action="store_true", help="open the dashboard in the browser afterwards")
    return parser


def load_cfg(config_path: str) -> dict[str, Any] | None:
    """The config, {} if the file does not exist, None (after printing why) if it is broken."""
    from runlog import config

    try:
        return config.load_config(config_path)
    except config.ConfigError as exc:
        if Path(config_path).exists():
            print(f"Error: {exc}", file=sys.stderr)
            return None
        print(f"Note: {config_path} not found, using defaults.", file=sys.stderr)
        return {}


def cmd_sync(cfg: dict[str, Any], reparse: bool = False) -> int:
    from runlog import config, db
    from runlog.sources.garmin_api import AuthError, GarminSource
    from runlog.sync import reparse_fit_files, run_sync

    if reparse:
        conn = db.connect(config.data_dir(cfg) / "runlog.db")
        try:
            print(f"Re-read {reparse_fit_files(conn)} FIT files.")
        finally:
            conn.close()
        return 0
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


def cmd_log(cfg: dict[str, Any], args: argparse.Namespace) -> int:
    from runlog import config, db
    from runlog.manual import EntryError, add_entry

    conn = db.connect(config.data_dir(cfg) / "runlog.db")
    try:
        add_entry(
            conn,
            args.date or date.today(),
            tendon=args.tendon,
            startup_pain=args.startup_pain,
            legs=args.legs.lower() if args.legs else None,
            hip_pain=args.hip,
            fuel_g=args.fuel,
            activity=args.activity,
            note=args.note,
        )
    except EntryError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    finally:
        conn.close()
    print("Saved.")
    return 0


def cmd_check(cfg: dict[str, Any], args: argparse.Namespace) -> int:
    from runlog import config, db
    from runlog.plan import PlanError, load_plan
    from runlog.report import build_report

    plan_path = Path((cfg.get("paths") or {}).get("plan_file") or "plan.yaml")
    try:
        plan = load_plan(plan_path) if plan_path.exists() else None
    except PlanError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    conn = db.connect(config.data_dir(cfg) / "runlog.db")
    try:
        print(build_report(conn, cfg, plan, args.date or date.today()))
    finally:
        conn.close()
    return 0


def cmd_build(cfg: dict[str, Any], args: argparse.Namespace) -> int:
    import webbrowser

    from runlog import config, db, tools
    from runlog.dashboard.build import build
    from runlog.plan import PlanError, load_plan

    plan_path = Path((cfg.get("paths") or {}).get("plan_file") or "plan.yaml")
    try:
        plan = load_plan(plan_path) if plan_path.exists() else None
    except PlanError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    try:
        conn = db.connect_readonly(config.data_dir(cfg) / "runlog.db")
    except FileNotFoundError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    try:
        html = build(tools.Context(conn, cfg, plan, args.date or date.today()))
    finally:
        conn.close()
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(html, encoding="utf-8")
    print(f"Dashboard: {output.resolve()}")
    if args.open:
        webbrowser.open(output.resolve().as_uri())
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.command is None:
        parser.print_help()
        return 0
    if args.command == "mcp":
        try:
            from runlog.mcp_server import build_server
        except ImportError:
            print("Error: the MCP server needs the extra: pip install -e '.[mcp]'", file=sys.stderr)
            return 1
        build_server(args.config).run("stdio")
        return 0
    if args.command in ("sync", "log", "check", "build"):
        cfg = load_cfg(args.config)
        if cfg is None:
            return 1
        if args.command == "sync":
            return cmd_sync(cfg, args.reparse)
        if args.command == "log":
            return cmd_log(cfg, args)
        if args.command == "build":
            return cmd_build(cfg, args)
        return cmd_check(cfg, args)
    stage = COMMANDS[args.command][1]
    print(f"runlog {args.command}: not implemented yet (roadmap stage {stage})", file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main())
