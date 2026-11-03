import sqlite3
from datetime import date

import pytest

from runlog import config, db, tools
from runlog.cli import main
from runlog.dashboard.build import collect
from runlog.demo import WEEKS, generate
from runlog.plan import load_plan

TODAY = date(2030, 3, 14)  # a Thursday


@pytest.fixture(scope="module")
def demo(tmp_path_factory):
    return generate(tmp_path_factory.mktemp("demo"), today=TODAY)


def context(target):
    cfg = config.load_config(target / "config.yaml")
    conn = db.connect_readonly(config.data_dir(cfg) / "runlog.db")
    return tools.Context(conn, cfg, load_plan(config.plan_path(cfg)), TODAY)


def test_demo_has_twelve_weeks_of_runs_and_health(demo):
    conn = sqlite3.connect(demo / "data" / "runlog.db")
    first, last, count = conn.execute(
        "SELECT min(start_time_local), max(start_time_local), count(*) FROM activities"
    ).fetchone()
    assert first[:10] == "2029-12-25"  # Tuesday of the first of twelve weeks ending with TODAY's week
    assert last[:10] < TODAY.isoformat()  # today's session has not been run yet
    assert count >= WEEKS * 4
    assert conn.execute("SELECT count(DISTINCT date) FROM daily_health").fetchone()[0] == WEEKS * 7 - 3
    assert conn.execute("SELECT count(*) FROM activity_samples").fetchone()[0] > 100_000
    assert conn.execute("SELECT count(*) FROM laps WHERE intensity = 'active'").fetchone()[0] > 0


def test_demo_is_deterministic(tmp_path):
    a = generate(tmp_path / "a", today=TODAY)
    b = generate(tmp_path / "b", today=TODAY)
    query = "SELECT id, distance_m, avg_hr FROM activities ORDER BY id"
    rows = [sqlite3.connect(p / "data" / "runlog.db").execute(query).fetchall() for p in (a, b)]
    assert rows[0] == rows[1]


def test_demo_shows_the_built_in_deviations(demo):
    dash = collect(context(demo))
    findings = [f for row in dash.plan_rows for f in row["findings"]]
    assert any(f.startswith("too fast") for f in findings)
    assert "last rep was the fastest" in findings
    assert all(c.empty is None for c in dash.charts)  # every chart has data
    assert dash.morning["level"] is not None


def test_demo_contains_nothing_personal(demo):
    text = (demo / "plan.yaml").read_text(encoding="utf-8") + (demo / "config.yaml").read_text(encoding="utf-8")
    conn = sqlite3.connect(demo / "data" / "runlog.db")
    names = {r[0] for r in conn.execute("SELECT DISTINCT name FROM activities")}
    assert names <= {"5 x 1000 m", "Easy run", "Easy run + strides"} | {n for n in names if n.startswith("Long run")}
    assert conn.execute("SELECT count(*) FROM raw_responses").fetchone()[0] == 0
    for word in ("Florence", "Lisbon", "Wanstrath", "Patella"):
        assert word not in text


def test_cli_demo(tmp_path):
    out = tmp_path / "site" / "index.html"
    assert main(["demo", "--output", str(out), "--data-dir", str(tmp_path / "data")]) == 0
    assert "Training Dashboard" in out.read_text(encoding="utf-8")


def test_config_paths_are_relative_to_the_config_file(tmp_path, monkeypatch):
    (tmp_path / "config.yaml").write_text("paths: {data_dir: d, plan_file: p.yaml}\n", encoding="utf-8")
    monkeypatch.chdir(tmp_path.parent)
    cfg = config.load_config(tmp_path / "config.yaml")
    assert config.data_dir(cfg) == tmp_path / "d"
    assert config.plan_path(cfg) == tmp_path / "p.yaml"
    assert config.data_dir({}).as_posix() == "data"
