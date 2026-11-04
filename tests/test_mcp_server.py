import asyncio
import sqlite3
import subprocess
import sys
import textwrap

import pytest

pytest.importorskip("mcp")

from runlog import db, tools  # noqa: E402
from runlog.mcp_server import Settings, build_server  # noqa: E402

TOOL_NAMES = {
    "get_recent_runs",
    "get_run_details",
    "get_weekly_volume",
    "get_intensity_distribution",
    "get_recovery_status",
    "get_warnings",
    "get_plan_status",
    "get_plan_progress",
    "get_zone_volume",
    "get_countdown",
    "get_manual_entries",
}


def test_tools_return_data(project):
    s = Settings(project / "config.yaml")
    (run,) = s.call(tools.get_recent_runs, days=7)
    assert run["distance_km"] == 8.0
    assert run["pace_min_per_km"] == "7:00"
    assert run["garmin_rpe_1_to_10"] == 3
    assert run["time_above_140_bpm_pct"] == 0

    details = s.call(tools.get_run_details, activity_id=1)
    assert details["plan"]["findings"] == []
    assert details["laps"][0]["pace_min_per_km"] == "6:57"
    assert s.call(tools.get_run_details, activity_id=99) == {"error": "no activity with id 99"}

    warnings = s.call(tools.get_warnings)
    assert warnings["morning_check"]["level"] == "green"
    assert s.call(tools.get_countdown)[0]["days"] == 10
    assert s.call(tools.get_plan_status)["sessions"][0]["status"] == "done"
    assert s.call(tools.get_recovery_status, days=3)[-1]["hrv_ms"] == 95
    assert s.call(tools.get_manual_entries)[0]["patellar_tendon_0_to_10"] == 1
    assert s.call(tools.get_weekly_volume)[-1]["distance_km"] >= 0
    assert s.call(tools.get_intensity_distribution)[0]["easy_below_140_bpm_pct"] == 100.0
    assert s.call(tools.get_zone_volume)[-1]["easy_km"] == 8.0
    progress = s.call(tools.get_plan_progress)
    assert progress["done_by_zone_km"]["easy"] == 8.0
    assert progress["zones"] == ["Easy ≤ 140", "Moderate 141–160", "Hard > 160"]


def test_server_registers_read_only_tools(project):
    server = build_server(project / "config.yaml")
    listed = asyncio.run(server.list_tools())
    assert {t.name for t in listed} == TOOL_NAMES
    assert all(t.annotations and t.annotations.read_only_hint for t in listed)
    assert not any(t.annotations.destructive_hint or t.annotations.open_world_hint for t in listed)


def test_server_works_from_another_directory(project, tmp_path_factory, monkeypatch):
    monkeypatch.chdir(tmp_path_factory.mktemp("elsewhere"))
    assert Settings(project / "config.yaml").call(tools.get_recent_runs)[0]["activity_id"] == 1


def test_database_is_read_only(project):
    conn = db.connect_readonly(project / "data" / "runlog.db")
    with pytest.raises(sqlite3.OperationalError):
        conn.execute("INSERT INTO sync_state (name, value) VALUES ('x', 'y')")
    with pytest.raises(sqlite3.OperationalError):
        conn.execute("DELETE FROM activities")


def test_import_does_not_load_garmin_client():
    code = "import sys, runlog.mcp_server; assert 'garmin_personal_api' not in sys.modules, 'garmin client imported'"
    result = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr


def test_tools_never_touch_the_api_key(project):
    """Run every tool with guards: reading the key variable or opening ~/.config/garmin fails the test."""
    code = textwrap.dedent(
        f"""
        import builtins, io, os, pathlib
        from runlog import tools
        from runlog.mcp_server import Settings

        KEY = "GARMIN_PERSONAL_API_KEY"

        class GuardedEnviron(type(os.environ)):
            def __getitem__(self, key):
                if key == KEY:
                    raise AssertionError("API key variable read")
                return super().__getitem__(key)

        os.environ.__class__ = GuardedEnviron
        real_open = builtins.open

        def guarded_open(file, *args, **kwargs):
            if ".config" in str(file).replace("\\\\", "/") and "garmin" in str(file):
                raise AssertionError(f"opened {{file}}")
            return real_open(file, *args, **kwargs)

        builtins.open = io.open = guarded_open
        s = Settings(r"{project / "config.yaml"}")
        for fn in (tools.get_recent_runs, tools.get_weekly_volume, tools.get_intensity_distribution,
                   tools.get_recovery_status, tools.get_warnings, tools.get_plan_status,
                   tools.get_countdown, tools.get_manual_entries, tools.get_plan_progress,
                   tools.get_zone_volume):
            s.call(fn)
        s.call(tools.get_run_details, activity_id=1)
        print("ok")
        """
    )
    env = {**__import__("os").environ, "GARMIN_PERSONAL_API_KEY": "secret-test-value"}
    result = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, env=env)
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "ok"
