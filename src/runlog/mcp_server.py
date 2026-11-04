"""Local, read-only MCP server (stdio) for Claude Code.

It only reads the SQLite database, config.yaml and plan.yaml. It never imports the Garmin
client and never reads the API key, the key file or GARMIN_PERSONAL_API_KEY.

    runlog --config <project>/config.yaml mcp
"""

from __future__ import annotations

import argparse
from collections.abc import Callable, Sequence
from datetime import date
from pathlib import Path
from typing import Any

from mcp.server.mcpserver import MCPServer
from mcp.types import ToolAnnotations

from runlog import config, db, tools
from runlog.config import DEFAULT_CONFIG_PATH, ConfigError, load_config
from runlog.plan import load_plan

READ_ONLY = ToolAnnotations(read_only_hint=True, destructive_hint=False, idempotent_hint=True, open_world_hint=False)

INSTRUCTIONS = (
    "Training data of one runner from Garmin (runs, per-second samples, laps, sleep, HRV, resting heart rate) "
    "plus manual morning checks and a training plan. All tools are read-only. Units are part of the field names. "
    "Start with get_warnings for today's status, get_recent_runs for an overview, get_run_details for one run."
)


class Settings:
    """Paths resolved against the config file's folder, so the server works from any working directory."""

    def __init__(self, config_path: str | Path) -> None:
        self.config_path = Path(config_path).resolve()
        try:
            self.config: dict[str, Any] = load_config(self.config_path)
        except ConfigError:
            if self.config_path.exists():
                raise
            self.config = {config.BASE_KEY: str(self.config_path.parent)}
        self.db_path = config.data_dir(self.config) / "runlog.db"
        self.plan_path = config.plan_path(self.config)

    def call(self, fn: Callable[..., Any], **kwargs: Any) -> Any:
        """Run a tool with a fresh read-only connection, so new syncs and plan edits show up immediately."""
        plan = load_plan(self.plan_path) if self.plan_path.exists() else None
        conn = db.connect_readonly(self.db_path)
        try:
            return fn(tools.Context(conn, self.config, plan, date.today()), **kwargs)
        finally:
            conn.close()


def build_server(config_path: str | Path = DEFAULT_CONFIG_PATH) -> MCPServer:
    settings = Settings(config_path)
    server = MCPServer(name="runlog", instructions=INSTRUCTIONS)

    @server.tool(annotations=READ_ONLY)
    def get_recent_runs(days: int = 14) -> list[dict[str, Any]]:
        """Runs of the last `days` days: distance, pace, heart rate, time above the easy cap, training effect,
        Garmin RPE and VO2max."""
        return settings.call(tools.get_recent_runs, days=days)

    @server.tool(annotations=READ_ONLY)
    def get_run_details(activity_id: int) -> dict[str, Any]:
        """One run in detail: laps (km splits or workout steps), aerobic decoupling, efficiency factor,
        Garmin zone times, fueling and the comparison with the planned session."""
        return settings.call(tools.get_run_details, activity_id=activity_id)

    @server.tool(annotations=READ_ONLY)
    def get_weekly_volume(weeks: int = 8) -> list[dict[str, Any]]:
        """Weekly running km, change against the previous week and the 3-week mean, longest run."""
        return settings.call(tools.get_weekly_volume, weeks=weeks)

    @server.tool(annotations=READ_ONLY)
    def get_intensity_distribution(weeks: int = 4) -> list[dict[str, Any]]:
        """Weekly share of easy time (below the heart rate cap from the config, target 80 %)."""
        return settings.call(tools.get_intensity_distribution, weeks=weeks)

    @server.tool(annotations=READ_ONLY)
    def get_recovery_status(days: int = 14) -> list[dict[str, Any]]:
        """Daily HRV and resting heart rate against the baseline, 7-day means, sleep, body battery, stress."""
        return settings.call(tools.get_recovery_status, days=days)

    @server.tool(annotations=READ_ONLY)
    def get_warnings() -> dict[str, Any]:
        """Today's morning check (traffic light per signal with advice), training warnings and
        deviations from the plan in the last 7 days."""
        return settings.call(tools.get_warnings)

    @server.tool(annotations=READ_ONLY)
    def get_plan_status(days_back: int = 7, days_ahead: int = 7) -> dict[str, Any]:
        """Planned sessions around today with status (done, moved, missed, upcoming), findings and weekly km."""
        return settings.call(tools.get_plan_status, days_back=days_back, days_ahead=days_ahead)

    @server.tool(annotations=READ_ONLY)
    def get_plan_progress() -> dict[str, Any]:
        """Km planned up to today against km run since the plan started, in total and per plan week,
        split into heart rate zones."""
        return settings.call(tools.get_plan_progress)

    @server.tool(annotations=READ_ONLY)
    def get_zone_volume(weeks: int = 8) -> list[dict[str, Any]]:
        """Running km and minutes per heart rate zone (zones from the config) for each week."""
        return settings.call(tools.get_zone_volume, weeks=weeks)

    @server.tool(annotations=READ_ONLY)
    def get_countdown() -> list[dict[str, Any]]:
        """Days until the upcoming races and tests."""
        return settings.call(tools.get_countdown)

    @server.tool(annotations=READ_ONLY)
    def get_manual_entries(days: int = 14) -> list[dict[str, Any]]:
        """Morning checks (patellar tendon, legs, hip) and fueling of the last `days` days."""
        return settings.call(tools.get_manual_entries, days=days)

    return server


def main(argv: Sequence[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="runlog-mcp", description="Read-only MCP server for runlog")
    parser.add_argument("--config", default=str(DEFAULT_CONFIG_PATH))
    args = parser.parse_args(argv)
    build_server(args.config).run("stdio")


if __name__ == "__main__":
    main()
