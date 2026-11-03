import json
import re
from datetime import date

from runlog import db, tools
from runlog.cli import main
from runlog.dashboard.build import build, collect
from runlog.plan import load_plan

CHART_IDS = {"volume", "longrun", "intensity", "decoupling", "efficiency", "vo2max", "hrv", "rhr", "sleep"}


def context(project, today=None):
    conn = db.connect_readonly(project / "data" / "runlog.db")
    return tools.Context(conn, {}, load_plan(project / "plan.yaml"), today or date.today())


def charts_json(html):
    return json.loads(re.search(r"const CHARTS = (.*);", html).group(1))


def test_collect(project):
    dash = collect(context(project))
    assert {c.id for c in dash.charts} == CHART_IDS
    assert dash.morning["level"] == "green"
    assert dash.plan_rows[0]["status"] == "done"
    assert dash.runs[0]["distance_km"] == 8.0
    efficiency = next(c for c in dash.charts if c.id == "efficiency")
    assert efficiency.empty is None  # the easy run counts
    decoupling = next(c for c in dash.charts if c.id == "decoupling")
    assert decoupling.empty == "No runs of 14 km or more yet."


def test_html_is_self_contained_and_themed(project):
    html = build(context(project))
    charts = charts_json(html)
    assert {c["id"] for c in charts} == CHART_IDS
    # Colors are theme tokens resolved in the browser, never fixed hex in the figures.
    figures = json.dumps([c["data"] for c in charts])
    assert "var(--series-1)" in figures
    assert not re.search(r"#[0-9a-fA-F]{6}", figures)
    assert "prefers-color-scheme: dark" in html and ':root[data-theme="dark"]' in html
    assert html.count("<summary>Table</summary>") == len(CHART_IDS)


def test_text_is_escaped(project):
    conn = db.connect(project / "data" / "runlog.db")
    conn.execute("UPDATE activities SET name = '<script>alert(1)</script>' WHERE id = 1")
    conn.commit()
    conn.close()
    html = build(context(project))
    assert "<script>alert(1)</script>" not in html


def test_empty_database(tmp_path):
    db.connect(tmp_path / "runlog.db").close()
    conn = db.connect_readonly(tmp_path / "runlog.db")
    html = build(tools.Context(conn, {}, None, date.today()))
    assert "No runs in the last 14 days." in html
    assert "No plan.yaml" in html


def test_cli_build_writes_file(project, monkeypatch):
    monkeypatch.chdir(project)
    out = project / "out" / "dash.html"
    assert main(["build", "--output", str(out)]) == 0
    assert out.read_text(encoding="utf-8").startswith("<!doctype html>")


def test_cli_build_without_database(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    assert main(["build"]) == 1
    assert "run 'runlog sync' first" in capsys.readouterr().err
