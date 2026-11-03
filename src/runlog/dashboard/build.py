"""Collect the data for the dashboard and render it into one static HTML file.

Charts are Plotly figures written as plain JSON. Colors are CSS tokens like "var(--series-1)",
which the page resolves for the active light or dark theme, so one file serves both modes.
All numbers come from runlog.tools, the same queries the MCP server answers with.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import date, timedelta
from importlib import resources
from typing import Any

from jinja2 import Environment, select_autoescape

from runlog import data, tools
from runlog.metrics import activity_date, is_run, week_start
from runlog.metrics.decoupling import decoupling_pct
from runlog.metrics.efficiency import efficiency_factor, is_easy_by_hr
from runlog.plan import TYPES

PLOTLY_JS = "https://cdn.jsdelivr.net/npm/plotly.js-dist-min@2.35.2/plotly.min.js"
HISTORY_DAYS = 365
RECOVERY_DAYS = 60
SLEEP_NIGHTS = 30
PLAN_DAYS_BACK = 14
PLAN_DAYS_AHEAD = 7

S1, S2, S3, S4 = (f"var(--series-{i})" for i in range(1, 5))
MUTED, PLAN, BAND, SURFACE = "var(--muted)", "var(--plan)", "var(--band)", "var(--surface-1)"


@dataclass
class Table:
    columns: list[str]
    rows: list[list[Any]]


@dataclass
class Chart:
    id: str
    title: str
    subtitle: str
    data: list[dict[str, Any]]
    layout: dict[str, Any]
    table: Table
    empty: str | None = None  # shown instead of the plot when there is nothing to draw


@dataclass
class Tile:
    label: str
    value: str
    detail: str = ""
    status: str | None = None  # green, yellow, red


@dataclass
class Dashboard:
    today: date
    hero: Tile
    tiles: list[Tile]
    morning: dict[str, Any]
    warnings: list[str]
    plan_rows: list[dict[str, Any]]
    plan_weeks: list[dict[str, Any]]
    runs: list[dict[str, Any]]
    charts: list[Chart] = field(default_factory=list)


# --- helpers -----------------------------------------------------------------


def _short(day: str | date) -> str:
    d = day if isinstance(day, date) else date.fromisoformat(str(day)[:10])
    return f"{d:%d.%m.}"


def _num(value: Any, digits: int = 1) -> str:
    if value is None:
        return "–"
    if isinstance(value, float):
        return f"{value:,.{digits}f}"
    return f"{value:,}"


def _bars(x: list[Any], y: list[Any], name: str, color: str, hover: str, **extra: Any) -> dict[str, Any]:
    return {
        "type": "bar",
        "x": x,
        "y": y,
        "name": name,
        "marker": {"color": color, "line": {"color": SURFACE, "width": 2}},
        "hovertemplate": hover + "<extra></extra>",
        **extra,
    }


def _line(x: list[Any], y: list[Any], name: str, color: str, hover: str, markers: bool = True) -> dict[str, Any]:
    return {
        "type": "scatter",
        "mode": "lines+markers" if markers else "lines",
        "x": x,
        "y": y,
        "name": name,
        "line": {"color": color, "width": 2, "shape": "linear"},
        "marker": {"color": color, "size": 8, "line": {"color": SURFACE, "width": 2}},
        "connectgaps": True,
        "hovertemplate": hover + "<extra></extra>",
    }


def _dots(x: list[Any], y: list[Any], name: str, color: str, hover: str) -> dict[str, Any]:
    trace = _line(x, y, name, color, hover)
    trace["mode"] = "markers"
    return trace


def _target_line(y: float, label: str) -> tuple[dict[str, Any], dict[str, Any]]:
    """A solid hairline at a target value with a direct label at the right edge."""
    shape = {
        "type": "line",
        "xref": "paper",
        "x0": 0,
        "x1": 1,
        "y0": y,
        "y1": y,
        "line": {"color": "var(--text-secondary)", "width": 1},
    }
    note = {
        "xref": "paper",
        "x": 1,
        "y": y,
        "text": label,
        "showarrow": False,
        "xanchor": "right",
        "yanchor": "bottom",
        "font": {"color": "var(--text-secondary)", "size": 11},
    }
    return shape, note


# --- data --------------------------------------------------------------------


def collect(ctx: tools.Context) -> Dashboard:
    cfg = ctx.config
    long_km = ctx.cfg("metrics", "long_run_min_km", 14)
    easy_cap = ctx.cfg("intensity", "easy_hr_max", 140)
    weeks = tools.get_weekly_volume(ctx, weeks=60)
    countdown = tools.get_countdown(ctx)
    warnings = tools.get_warnings(ctx)
    recovery = tools.get_recovery_status(ctx, days=RECOVERY_DAYS)
    runs = tools.get_recent_runs(ctx, days=HISTORY_DAYS)
    plan_status = tools.get_plan_status(ctx, PLAN_DAYS_BACK, PLAN_DAYS_AHEAD) if ctx.plan else None

    # Hero: this week's km against the plan.
    this_week = weeks[-1] if weeks else None
    plan_week = next((w for w in (plan_status or {}).get("weeks", []) if w["status"] == "in progress"), None)
    planned = ""
    if plan_week:
        low, high = plan_week["planned_km"]
        planned = f"of {low:g} km planned" if low == high else f"of {low:g}–{high:g} km planned"
    hero = Tile(
        "This week",
        f"{this_week['distance_km']:.1f} km" if this_week else "0 km",
        f"{planned}{' · ' if planned else ''}{this_week['runs'] if this_week else 0} runs",
    )

    check = warnings["morning_check"]
    last_rec = recovery[-1] if recovery else {}
    vo2 = next((r["vo2max"] for r in reversed(runs) if r.get("vo2max")), None)
    tiles = [
        Tile("Morning check", (check["level"] or "no data").capitalize(), check.get("advice") or "", check["level"]),
        Tile(
            "HRV 7-day mean",
            f"{_num(last_rec.get('hrv_7d_ms'), 0)} ms",
            _baseline_text(last_rec.get("hrv_baseline_ms")),
        ),
        Tile("Resting HR 7-day mean", f"{_num(last_rec.get('resting_hr_7d_bpm'), 1)} bpm"),
        Tile("VO2max", _num(vo2), "from the latest run"),
    ]
    upcoming = [e for e in countdown if e["days"] >= 0][:3]
    tiles += [Tile(e["event"], "today" if e["days"] == 0 else f"{e['days']} days", _event_detail(e)) for e in upcoming]

    plan_rows = []
    for s in (plan_status or {}).get("sessions", []):
        plan_rows.append(
            {
                "date": _short(s["date"]),
                "weekday": date.fromisoformat(s["date"]).strftime("%a"),
                "type": s["type"],
                "session": s["session"],
                "planned": _km_range(s["planned_km"]),
                "actual": f"{s['actual_km']:g} km" if s["actual_km"] is not None else "",
                "status": s["status"],
                "findings": s["findings"],
                "today": s["date"] == ctx.today.isoformat(),
            }
        )

    dash = Dashboard(
        today=ctx.today,
        hero=hero,
        tiles=tiles,
        morning=check,
        warnings=warnings["training"],
        plan_rows=plan_rows,
        plan_weeks=(plan_status or {}).get("weeks", []),
        runs=list(reversed([r for r in runs if r["date"] >= (ctx.today - timedelta(days=13)).isoformat()])),
    )
    dash.charts = [
        weekly_volume_chart(weeks, ctx),
        long_run_chart(weeks, ctx, long_km),
        intensity_chart(tools.get_intensity_distribution(ctx, weeks=60), easy_cap),
        decoupling_chart(ctx, long_km),
        efficiency_chart(ctx, easy_cap),
        vo2max_chart(runs),
        hrv_chart(recovery),
        resting_hr_chart(recovery, cfg),
        sleep_chart(ctx),
    ]
    return dash


def _baseline_text(baseline: Any) -> str:
    if not baseline or None in baseline:
        return ""
    return f"baseline {baseline[0]:g}–{baseline[1]:g} ms"


def _event_detail(event: dict[str, Any]) -> str:
    when = date.fromisoformat(event["date"])
    return f"{when:%a %d.%m.%Y}" + (f" · goal {event['goal']}" if event.get("goal") else "")


def _km_range(value: Any) -> str:
    if not value:
        return ""
    low, high = value
    return f"{low:g} km" if low == high else f"{low:g}–{high:g} km"


def _plan_week_km(ctx: tools.Context) -> dict[str, float]:
    return {w.start.isoformat(): w.km[1] for w in ctx.plan.weeks} if ctx.plan else {}


def _plan_long_km(ctx: tools.Context) -> dict[str, float]:
    result: dict[str, float] = {}
    for s in ctx.plan.sessions if ctx.plan else []:
        if s.type == "L" and s.km:
            key = week_start(s.date).isoformat()
            result[key] = max(result.get(key, 0), s.km[1])
    return result


# --- charts ------------------------------------------------------------------


def weekly_volume_chart(weeks: list[dict[str, Any]], ctx: tools.Context) -> Chart:
    plan = _plan_week_km(ctx)
    x = [_short(w["week_start"]) for w in weeks]
    data_ = [
        _bars(
            x,
            [w["distance_km"] for w in weeks],
            "Run",
            S1,
            "Week of %{x}: %{y:.1f} km<br>%{customdata[0]} runs · %{customdata[1]} vs 3-week mean",
            customdata=[[w["runs"], _signed(w["change_vs_3_week_mean_pct"])] for w in weeks],
        )
    ]
    if plan:
        data_.append(
            _bars(x, [plan.get(w["week_start"]) for w in weeks], "Plan", PLAN, "Plan, week of %{x}: %{y:g} km")
        )
    rows = [
        [
            w["week_start"],
            w["distance_km"],
            plan.get(w["week_start"], "–"),
            w["runs"],
            _signed(w["change_vs_prev_week_pct"]),
            _signed(w["change_vs_3_week_mean_pct"]),
        ]
        for w in weeks
    ]
    return Chart(
        "volume",
        "Weekly distance",
        "Running km per week (Mon–Sun) against the plan",
        data_,
        {"barmode": "group", "yaxis": {"ticksuffix": " km"}},
        Table(["Week", "km", "Plan km", "Runs", "vs prev. week", "vs 3-week mean"], rows),
    )


def long_run_chart(weeks: list[dict[str, Any]], ctx: tools.Context, long_km: float) -> Chart:
    plan = _plan_long_km(ctx)
    x = [_short(w["week_start"]) for w in weeks]
    data_ = [_bars(x, [w["longest_run_km"] for w in weeks], "Longest run", S1, "Week of %{x}: %{y:.1f} km")]
    if plan:
        data_.append(_bars(x, [plan.get(w["week_start"]) for w in weeks], "Planned long run", PLAN, "Plan: %{y:g} km"))
    rows = [[w["week_start"], w["longest_run_km"], plan.get(w["week_start"], "–")] for w in weeks]
    return Chart(
        "longrun",
        "Long run progression",
        f"Longest run per week; long runs count from {long_km:g} km",
        data_,
        {"barmode": "group", "yaxis": {"ticksuffix": " km"}},
        Table(["Week", "Longest run km", "Planned long run km"], rows),
    )


def intensity_chart(weeks: list[dict[str, Any]], easy_cap: float) -> Chart:
    key = f"easy_below_{easy_cap}_bpm_pct"
    x = [w["week_start"] for w in weeks]
    trace = _line(
        x,
        [w[key] for w in weeks],
        "Easy share",
        S1,
        "Week of %{x|%d.%m.}: %{y:.0f} % easy<br>%{customdata[0]} min easy · %{customdata[1]} min hard",
    )
    trace["customdata"] = [[w["easy_min"], w["hard_min"]] for w in weeks]
    shape, note = _target_line(80, "Target 80 %")
    rows = [[w["week_start"], w[key], w["easy_min"], w["hard_min"], w["easy_by_garmin_zones_pct"]] for w in weeks]
    return Chart(
        "intensity",
        "Intensity distribution",
        f"Share of moving time at or below {easy_cap:g} bpm per week",
        [trace],
        {
            "yaxis": {"range": [0, 105], "ticksuffix": " %"},
            "xaxis": {"type": "date", "tickformat": "%d.%m."},
            "shapes": [shape],
            "annotations": [note],
            "showlegend": False,
        },
        Table(["Week", "Easy %", "Easy min", "Hard min", "Easy % by Garmin zones"], rows),
    )


def decoupling_chart(ctx: tools.Context, long_km: float) -> Chart:
    warmup_s = ctx.cfg("metrics", "decoupling_warmup_min", 10) * 60
    points = []
    for a in data.activities(ctx.conn):
        if is_run(a) and activity_date(a) <= ctx.today and (a.get("distance_m") or 0) >= long_km * 1000:
            value = decoupling_pct(data.samples(ctx.conn, a["id"]), warmup_s)
            if value is not None:
                points.append((a["start_time_local"][:10], value, round(a["distance_m"] / 1000, 1)))
    trace = _line(
        [p[0] for p in points],
        [p[1] for p in points],
        "Decoupling",
        S1,
        "%{x|%d.%m.}: %{y:.1f} %<br>%{customdata} km",
    )
    trace["customdata"] = [p[2] for p in points]
    shape, note = _target_line(5, "Good below 5 %")
    return Chart(
        "decoupling",
        "Aerobic decoupling of long runs",
        f"Pa:HR drift between the two halves, runs from {long_km:g} km, warm-up excluded",
        [trace],
        {
            "yaxis": {"ticksuffix": " %"},
            "xaxis": {"type": "date", "tickformat": "%d.%m."},
            "shapes": [shape],
            "annotations": [note],
            "showlegend": False,
        },
        Table(["Date", "Decoupling %", "km"], [list(p) for p in points]),
        empty=None if points else f"No runs of {long_km:g} km or more yet.",
    )


def efficiency_chart(ctx: tools.Context, easy_cap: float) -> Chart:
    share = ctx.cfg("intensity", "easy_share_min", 0.8)
    points = []
    for a in data.activities(ctx.conn):
        if not is_run(a) or activity_date(a) > ctx.today:
            continue
        ef = efficiency_factor(a)
        if ef is not None and is_easy_by_hr(a, data.samples(ctx.conn, a["id"]), easy_cap, share):
            points.append((a["start_time_local"][:10], ef, round((a.get("distance_m") or 0) / 1000, 1)))
    trace = _line(
        [p[0] for p in points],
        [p[1] for p in points],
        "Efficiency factor",
        S1,
        "%{x|%d.%m.}: %{y:.3f} m/min per bpm<br>%{customdata} km",
    )
    trace["customdata"] = [p[2] for p in points]
    return Chart(
        "efficiency",
        "Efficiency factor of easy runs",
        f"Speed (m/min) per heartbeat on runs with at least {share:.0%} of moving time ≤ {easy_cap:g} bpm; "
        "rising means fitter",
        [trace],
        {"xaxis": {"type": "date", "tickformat": "%d.%m."}, "yaxis": {"rangemode": "normal"}, "showlegend": False},
        Table(["Date", "EF", "km"], [list(p) for p in points]),
        empty=None if points else "No easy runs yet.",
    )


def vo2max_chart(runs: list[dict[str, Any]]) -> Chart:
    points = [(r["date"], r["vo2max"]) for r in runs if r.get("vo2max")]
    return Chart(
        "vo2max",
        "VO2max",
        "Garmin's estimate after each run (ml/kg/min)",
        [_line([p[0] for p in points], [p[1] for p in points], "VO2max", S1, "%{x|%d.%m.}: %{y:.1f}")],
        {"xaxis": {"type": "date", "tickformat": "%d.%m."}, "yaxis": {"rangemode": "normal"}, "showlegend": False},
        Table(["Date", "VO2max"], [list(p) for p in points]),
        empty=None if points else "No VO2max values yet.",
    )


def hrv_chart(recovery: list[dict[str, Any]]) -> Chart:
    x = [r["date"] for r in recovery]
    low = [(r["hrv_baseline_ms"] or [None, None])[0] for r in recovery]
    high = [(r["hrv_baseline_ms"] or [None, None])[1] for r in recovery]
    band_hover = "Baseline %{y:g} ms<extra></extra>"
    data_ = [
        {
            "type": "scatter",
            "mode": "lines",
            "x": x,
            "y": low,
            "line": {"width": 0},
            "hovertemplate": band_hover,
            "showlegend": False,
            "name": "Baseline low",
        },
        {
            "type": "scatter",
            "mode": "lines",
            "x": x,
            "y": high,
            "line": {"width": 0},
            "fill": "tonexty",
            "fillcolor": BAND,
            "name": "Baseline range",
            "hovertemplate": band_hover,
        },
        _dots(x, [r["hrv_ms"] for r in recovery], "Night", MUTED, "%{x|%d.%m.}: %{y} ms"),
        _line(x, [r["hrv_7d_ms"] for r in recovery], "7-day mean", S1, "7-day mean %{y:.0f} ms", markers=False),
    ]
    rows = [
        [r["date"], r["hrv_ms"], r["hrv_7d_ms"], _baseline_text(r["hrv_baseline_ms"]), r["hrv_7d_vs_baseline"]]
        for r in recovery
    ]
    return Chart(
        "hrv",
        "HRV",
        "Nightly average and 7-day mean against Garmin's baseline range",
        data_,
        {
            "xaxis": {"type": "date", "tickformat": "%d.%m."},
            "yaxis": {"ticksuffix": " ms", "rangemode": "normal"},
            "hovermode": "x unified",
        },
        Table(["Date", "HRV ms", "7-day mean", "Baseline", "7-day vs baseline"], rows),
    )


def resting_hr_chart(recovery: list[dict[str, Any]], cfg: dict[str, Any]) -> Chart:
    x = [r["date"] for r in recovery]
    data_ = [
        _dots(x, [r["resting_hr_bpm"] for r in recovery], "Day", MUTED, "%{x|%d.%m.}: %{y} bpm"),
        _line(x, [r["resting_hr_7d_bpm"] for r in recovery], "7-day mean", S1, "7-day mean %{y:.1f} bpm", False),
    ]
    layout: dict[str, Any] = {
        "xaxis": {"type": "date", "tickformat": "%d.%m."},
        "yaxis": {"ticksuffix": " bpm", "rangemode": "normal"},
        "hovermode": "x unified",
    }
    yellow = ((cfg.get("morning_check") or {}).get("resting_hr_bpm") or {}).get("yellow", 43)
    shape, note = _target_line(yellow, f"Yellow from {yellow:g} bpm")
    layout["shapes"], layout["annotations"] = [shape], [note]
    rows = [[r["date"], r["resting_hr_bpm"], r["resting_hr_7d_bpm"], r["resting_hr_vs_baseline_bpm"]] for r in recovery]
    return Chart(
        "rhr",
        "Resting heart rate",
        "Daily value and 7-day mean",
        data_,
        layout,
        Table(["Date", "Resting HR", "7-day mean", "vs baseline"], rows),
    )


def sleep_chart(ctx: tools.Context) -> Chart:
    since = (ctx.today - timedelta(days=SLEEP_NIGHTS - 1)).isoformat()
    nights = [
        d for d in data.daily_health(ctx.conn) if since <= d["date"] <= ctx.today.isoformat() and d.get("sleep_s")
    ]
    x = [d["date"] for d in nights]
    stages = [("Deep", "deep_s", S1), ("REM", "rem_s", S2), ("Light", "light_s", S3), ("Awake", "awake_s", S4)]
    data_ = [
        _bars(
            x,
            [round((d.get(key) or 0) / 3600, 2) for d in nights],
            name,
            color,
            f"{name} %{{y:.1f}} h",
        )
        for name, key, color in stages
    ]
    data_[0]["customdata"] = [[round(d["sleep_s"] / 3600, 1), d.get("sleep_score") or "–"] for d in nights]
    data_[0]["hovertemplate"] = (
        "Night to %{x|%d.%m.}: %{customdata[0]} h asleep, score %{customdata[1]}<br>Deep %{y:.1f} h<extra></extra>"
    )
    rows = [
        [
            d["date"],
            round(d["sleep_s"] / 3600, 2),
            d.get("sleep_score"),
            *(round((d.get(k) or 0) / 3600, 2) for _, k, _ in stages),
        ]
        for d in nights
    ]
    return Chart(
        "sleep",
        "Sleep",
        f"Hours per night by stage, last {SLEEP_NIGHTS} nights",
        data_,
        {
            "barmode": "stack",
            "xaxis": {"type": "date", "tickformat": "%d.%m."},
            "yaxis": {"ticksuffix": " h"},
            "legend": {"traceorder": "normal"},
            "hovermode": "x unified",
        },
        Table(["Night ending", "Asleep h", "Score", "Deep h", "REM h", "Light h", "Awake h"], rows),
        empty=None if nights else "No sleep data yet.",
    )


def _signed(value: Any) -> str:
    return "–" if value is None else f"{value:+.0f} %"


# --- render ------------------------------------------------------------------


def render(dash: Dashboard) -> str:
    env = Environment(autoescape=select_autoescape(default=True), trim_blocks=True, lstrip_blocks=True)
    template = env.from_string((resources.files("runlog.dashboard") / "template.html.j2").read_text(encoding="utf-8"))
    return template.render(
        d=dash,
        charts=[asdict(c) for c in dash.charts],
        plotly_js=PLOTLY_JS,
        types=TYPES,
    )


def build(ctx: tools.Context) -> str:
    return render(collect(ctx))
