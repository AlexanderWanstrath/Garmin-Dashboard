"""Collect the data for the dashboard and render it into one static HTML file.

The file has three pages, switched with tabs: overview (morning check, plan of the coming days,
recent runs, volume), marathon plan (planned against run km, per zone) and health (HRV, resting
heart rate, sleep, VO2max, decoupling, efficiency).

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
from runlog.metrics import activity_date, is_run, mean, week_start
from runlog.metrics.decoupling import decoupling_pct
from runlog.metrics.efficiency import efficiency_factor, is_easy_by_hr
from runlog.plan import TYPES

PLOTLY_JS = "https://cdn.jsdelivr.net/npm/plotly.js-dist-min@2.35.2/plotly.min.js"
HISTORY_DAYS = 365
RECOVERY_DAYS = 60
SLEEP_NIGHTS = 30
PLAN_DAYS_BACK = 14
PLAN_DAYS_AHEAD = 7
ALL_DAYS = 3650

S1, S2, S3, S4 = (f"var(--series-{i})" for i in range(1, 5))
MUTED, PLAN, BAND, SURFACE = "var(--muted)", "var(--plan)", "var(--band)", "var(--surface-1)"
# Heart rate zones from easy to hard: green, amber, orange, then blue for a fourth zone.
ZONE_COLORS = [S3, S4, S2, S1]


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
    note: str = ""  # plain-language explanation below the subtitle
    height: int = 280
    wide: bool = False  # spans both grid columns


@dataclass
class Tile:
    label: str
    value: str
    detail: str = ""
    status: str | None = None  # green, yellow, red


@dataclass
class Dashboard:
    today: date
    week: Tile
    countdown: list[Tile]
    morning: dict[str, Any]
    wellness: list[Tile]  # sleep and body battery next to the morning check
    advice: list[str]  # warnings and recommendations below the morning check
    plan_rows: list[dict[str, Any]]
    runs: list[dict[str, Any]]
    progress: dict[str, Any] | None = None
    plan_weeks: list[dict[str, Any]] = field(default_factory=list)  # all plan weeks with their sessions
    health_tiles: list[Tile] = field(default_factory=list)
    overview_charts: list[Chart] = field(default_factory=list)
    plan_charts: list[Chart] = field(default_factory=list)
    health_charts: list[Chart] = field(default_factory=list)


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


def _zone_keys(ctx: tools.Context) -> list[tuple[str, str, str]]:
    """(field prefix, label, color) per heart rate zone."""
    zone_list = tools.zones(ctx)
    labels = tools.zone_labels(zone_list)
    colors = ZONE_COLORS + [MUTED] * max(0, len(zone_list) - len(ZONE_COLORS))
    return [(z["name"].lower(), label, color) for z, label, color in zip(zone_list, labels, colors, strict=False)]


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
    zone_weeks = tools.get_zone_volume(ctx, weeks=60)
    plan_status = tools.get_plan_status(ctx, PLAN_DAYS_BACK, PLAN_DAYS_AHEAD) if ctx.plan else None
    progress = tools.get_plan_progress(ctx) if ctx.plan and ctx.plan.sessions else None

    dash = Dashboard(
        today=ctx.today,
        week=_week_tile(weeks, plan_status),
        countdown=[
            Tile(e["event"], "today" if e["days"] == 0 else f"{e['days']} days", _event_detail(e))
            for e in countdown
            if e["days"] >= 0
        ][:3],
        morning=warnings["morning_check"],
        wellness=_wellness(ctx),
        advice=_advice(warnings),
        plan_rows=[_plan_row(s, ctx.today) for s in (plan_status or {}).get("sessions", [])],
        runs=list(reversed([r for r in runs if r["date"] >= (ctx.today - timedelta(days=13)).isoformat()])),
        progress=progress,
        plan_weeks=_plan_weeks(ctx, progress),
        health_tiles=_health_tiles(ctx, recovery, runs),
    )
    dash.overview_charts = [
        long_run_chart(weeks, ctx, long_km),
        weekly_volume_chart(weeks, ctx),
        intensity_chart(zone_weeks, ctx, easy_cap),
    ]
    if progress:
        dash.plan_charts = [plan_to_date_chart(progress, ctx), plan_weeks_chart(progress, ctx)]
    dash.health_charts = [
        hrv_chart(recovery),
        resting_hr_chart(recovery, cfg),
        sleep_chart(ctx),
        vo2max_chart(runs),
        decoupling_chart(ctx, long_km),
        efficiency_chart(ctx, easy_cap),
    ]
    return dash


def _week_tile(weeks: list[dict[str, Any]], plan_status: dict[str, Any] | None) -> Tile:
    this_week = weeks[-1] if weeks and weeks[-1]["in_progress"] else None
    plan_week = next((w for w in (plan_status or {}).get("weeks", []) if w["status"] == "in progress"), None)
    detail = f"{this_week['runs'] if this_week else 0} runs"
    if plan_week:
        detail = f"of {_km_range(plan_week['planned_km'])} planned · " + detail
    return Tile("This week", f"{this_week['distance_km']:.1f} km" if this_week else "0 km", detail)


def _wellness(ctx: tools.Context) -> list[Tile]:
    today = next((d for d in data.daily_health(ctx.conn) if d["date"] == ctx.today.isoformat()), {})
    sleep_detail = []
    if today.get("sleep_score_quality"):
        sleep_detail.append(str(today["sleep_score_quality"]).replace("_", " ").lower())
    if today.get("sleep_s"):
        hours, minutes = divmod(round(today["sleep_s"] / 60), 60)
        sleep_detail.append(f"{hours} h {minutes:02d} min asleep")
    battery_detail = f"now {today['body_battery_latest']}" if today.get("body_battery_latest") is not None else ""
    return [
        Tile("Sleep score", _num(today.get("sleep_score")), " · ".join(sleep_detail)),
        Tile(
            "Body Battery",
            _num(today.get("body_battery_max")),
            "highest today" + (f" · {battery_detail}" if battery_detail else ""),
        ),
    ]


def _advice(warnings: dict[str, Any]) -> list[str]:
    check = warnings["morning_check"]
    items = [check["advice"]] if check.get("advice") else []
    items += warnings["training"]
    for d in warnings.get("plan_deviations_last_7_days", []):
        what = "; ".join(d["findings"]) if d["findings"] else d["status"]
        items.append(f"{_short(d['date'])} {d['session']}: {what}")
    return items


def _plan_row(s: dict[str, Any], today: date) -> dict[str, Any]:
    day = date.fromisoformat(s["date"])
    actual_km = f"{s['actual_km']:g} km" if s["actual_km"] is not None else ""
    if actual_km and len(s.get("activity_ids") or []) > 1:
        actual_km += f" ({len(s['activity_ids'])} runs)"
    if s["status"] == "moved" and s.get("actual_date"):
        actual_km += f", on {_short(s['actual_date'])}"
    return {
        "date": _short(day),
        "weekday": day.strftime("%a"),
        "type": s["type"],
        "session": s["session"],
        "target": s.get("target") or "",
        "planned": _km_range(s["planned_km"]),
        "actual_km": actual_km,
        "actual": s.get("actual") or "",
        "status": s["status"],
        "findings": s["findings"],
        "today": day == today,
    }


def _plan_weeks(ctx: tools.Context, progress: dict[str, Any] | None) -> list[dict[str, Any]]:
    """Every plan week with its sessions, for the table on the plan page."""
    if not progress:
        return []
    status = tools.get_plan_status(ctx, ALL_DAYS, ALL_DAYS)
    rows = [_plan_row(s, ctx.today) for s in status["sessions"]]
    result = []
    for w in progress["weeks"]:
        start = date.fromisoformat(w["week_start"])
        result.append(
            {
                **w,
                "title": f"Week of {_short(start)}" + (f" · {w['label']}" if w["label"] else ""),
                "planned": _km_range(w["planned_km"]),
                "current": start <= ctx.today < start + timedelta(days=7),
                "sessions": [
                    r
                    for r, s in zip(rows, status["sessions"], strict=True)
                    if week_start(date.fromisoformat(s["date"])) == start
                ],
            }
        )
    return result


def _health_tiles(ctx: tools.Context, recovery: list[dict[str, Any]], runs: list[dict[str, Any]]) -> list[Tile]:
    last = recovery[-1] if recovery else {}
    week = recovery[-7:]
    vo2 = next((r for r in reversed(runs) if r.get("vo2max")), None)
    sleep = mean([r["sleep_score"] for r in week])
    battery = mean([r["body_battery_max"] for r in week])
    return [
        Tile("HRV 7-day mean", f"{_num(last.get('hrv_7d_ms'), 0)} ms", _baseline_text(last.get("hrv_baseline_ms"))),
        Tile("Resting HR 7-day mean", f"{_num(last.get('resting_hr_7d_bpm'), 1)} bpm"),
        Tile("VO2max", _num(vo2["vo2max"]) if vo2 else "–", f"run of {_short(vo2['date'])}" if vo2 else ""),
        Tile("Sleep score 7-day mean", _num(sleep, 0)),
        Tile("Body Battery 7-day mean", _num(battery, 0), "highest value per day"),
    ]


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
    weeks = (ctx.plan.previous_weeks + ctx.plan.weeks) if ctx.plan else []
    return {w.start.isoformat(): w.km[1] for w in weeks}


def _plan_long_km(ctx: tools.Context) -> dict[str, float]:
    result: dict[str, float] = {}
    for s in ctx.plan.sessions if ctx.plan else []:
        if s.type == "L" and s.km:
            key = week_start(s.date).isoformat()
            result[key] = max(result.get(key, 0), s.km[1])
    return result


# --- overview charts ---------------------------------------------------------


def weekly_volume_chart(weeks: list[dict[str, Any]], ctx: tools.Context) -> Chart:
    plan = _plan_week_km(ctx)
    x = [_short(w["week_start"]) for w in weeks]
    data_ = []
    if plan:
        data_.append(
            _bars(x, [plan.get(w["week_start"]) for w in weeks], "Plan", PLAN, "Plan, week of %{x}: %{y:g} km")
        )
    data_.append(
        _bars(
            x,
            [w["distance_km"] for w in weeks],
            "Run",
            S1,
            "Week of %{x}: %{y:.1f} km<br>%{customdata[0]} runs · %{customdata[1]} vs 3-week mean",
            customdata=[[w["runs"], _signed(w["change_vs_3_week_mean_pct"])] for w in weeks],
        )
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
        "Running km per week (Mon–Sun); plan in gray, including an earlier plan if plan.yaml lists one",
        data_,
        {"barmode": "group", "yaxis": {"ticksuffix": " km"}},
        Table(["Week", "km", "Plan km", "Runs", "vs prev. week", "vs 3-week mean"], rows),
    )


def long_run_chart(weeks: list[dict[str, Any]], ctx: tools.Context, long_km: float) -> Chart:
    plan = _plan_long_km(ctx)
    x = [_short(w["week_start"]) for w in weeks]
    data_ = []
    if plan:
        data_.append(_bars(x, [plan.get(w["week_start"]) for w in weeks], "Planned long run", PLAN, "Plan: %{y:g} km"))
    data_.append(_bars(x, [w["longest_run_km"] for w in weeks], "Longest run", S1, "Week of %{x}: %{y:.1f} km"))
    rows = [[w["week_start"], w["longest_run_km"], plan.get(w["week_start"], "–")] for w in weeks]
    return Chart(
        "longrun",
        "Long run progression",
        f"Longest run per week; long runs count from {long_km:g} km",
        data_,
        {"barmode": "group", "yaxis": {"ticksuffix": " km"}},
        Table(["Week", "Longest run km", "Planned long run km"], rows),
    )


def intensity_chart(zone_weeks: list[dict[str, Any]], ctx: tools.Context, easy_cap: float) -> Chart:
    keys = _zone_keys(ctx)
    x = [w["week_start"] for w in zone_weeks]
    totals = [sum(w[f"{k}_min"] for k, _, _ in keys) for w in zone_weeks]
    data_ = []
    for key, label, color in keys:
        minutes = [w[f"{key}_min"] for w in zone_weeks]
        trace = _bars(
            x,
            [round(m / t * 100, 1) if t else None for m, t in zip(minutes, totals, strict=True)],
            label,
            color,
            f"Week of %{{x|%d.%m.}}<br>{label} bpm: %{{y:.0f}} % · %{{customdata}} min",
            customdata=minutes,
        )
        data_.append(trace)
    shape, note = _target_line(80, "Target: 80 % easy")
    rows = [[w["week_start"], *(w[f"{k}_min"] for k, _, _ in keys), t] for w, t in zip(zone_weeks, totals, strict=True)]
    return Chart(
        "intensity",
        "Intensity distribution",
        f"Share of moving time per heart rate zone and week; the easy part (≤ {easy_cap:g} bpm) should reach 80 %",
        data_,
        {
            "barmode": "stack",
            "yaxis": {"range": [0, 100], "ticksuffix": " %"},
            "xaxis": {"type": "date", "tickformat": "%d.%m."},
            "shapes": [shape],
            "annotations": [note],
            "legend": {"traceorder": "normal"},
            "bargap": 0.3,
        },
        Table(["Week", *(f"{label} min" for _, label, _ in keys), "Total min"], rows),
        empty=None if zone_weeks else "No runs with heart rate yet.",
        wide=True,
    )


# --- plan charts -------------------------------------------------------------


def plan_to_date_chart(progress: dict[str, Any], ctx: tools.Context) -> Chart:
    keys = _zone_keys(ctx)
    planned, done = progress["planned_km_to_date"], progress["done_km"]
    data_ = [_bars([planned], ["Plan"], "Planned to date", PLAN, "Planned up to today: %{x:.1f} km", orientation="h")]
    for key, label, color in keys:
        km = progress["done_by_zone_km"].get(key, 0)
        data_.append(
            _bars([km], ["Run"], label, color, f"{label} bpm: %{{x:.1f}} km of {done:.1f} km", orientation="h")
        )
    rows = [["Planned to date", planned]] + [[label, progress["done_by_zone_km"].get(k, 0)] for k, label, _ in keys]
    rows.append(["Run in total", done])
    diff = done - planned
    return Chart(
        "plan-to-date",
        "Plan up to today",
        f"{done:.1f} km run against {planned:.1f} km planned since {_short(progress['plan_start'])} "
        f"({diff:+.1f} km), run km split into heart rate zones",
        data_,
        {
            "barmode": "stack",
            "xaxis": {"ticksuffix": " km", "showgrid": True, "rangemode": "tozero"},
            "yaxis": {"showgrid": False, "autorange": "reversed"},
            "legend": {"traceorder": "normal"},
            "bargap": 0.35,
            "hovermode": "closest",
        },
        Table(["", "km"], rows),
        height=200,
        wide=True,
    )


def plan_weeks_chart(progress: dict[str, Any], ctx: tools.Context) -> Chart:
    """Planned (gray) next to run km stacked by zone. Grouped and stacked at once needs explicit bases."""
    keys = _zone_keys(ctx)
    weeks = progress["weeks"]
    x = [_short(w["week_start"]) + (f" {w['label']}" if w["label"] else "") for w in weeks]
    data_ = [
        _bars(
            x,
            [w["planned_km"][1] for w in weeks],
            "Plan",
            PLAN,
            "%{x}: %{customdata} planned",
            customdata=[_km_range(w["planned_km"]) for w in weeks],
            offsetgroup="plan",
        )
    ]
    base = [0.0] * len(weeks)
    for key, label, color in keys:
        km = [None if w["future"] else w[f"{key}_km"] for w in weeks]
        data_.append(
            _bars(
                x,
                km,
                label,
                color,
                f"%{{x}}<br>{label} bpm: %{{y:.1f}} km",
                base=list(base),
                offsetgroup="run",
            )
        )
        base = [b + (k or 0) for b, k in zip(base, km, strict=True)]
    rows = [
        [w["week_start"], w["label"] or "", _km_range(w["planned_km"]), w["sessions_km"], w["done_km"]]
        + [w[f"{k}_km"] for k, _, _ in keys]
        for w in weeks
    ]
    return Chart(
        "plan-weeks",
        "Weekly km against the plan",
        "Planned week (gray) next to the km run, split into heart rate zones",
        data_,
        {"barmode": "group", "yaxis": {"ticksuffix": " km"}, "legend": {"traceorder": "normal"}},
        Table(["Week", "Label", "Planned", "Sessions km", "Run km", *(f"{label} km" for _, label, _ in keys)], rows),
        wide=True,
    )


# --- health charts -----------------------------------------------------------


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
        f"Runs from {long_km:g} km, first {warmup_s // 60:g} minutes left out",
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
        note="How much the heart rate drifts up in the second half of a long run at the same pace. "
        "Below 5 % means your aerobic base carries the distance; higher values mean you got tired, "
        "it was hot, or you lacked fuel or fluids.",
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
        f"Runs with at least {share:.0%} of moving time ≤ {easy_cap:g} bpm",
        [trace],
        {"xaxis": {"type": "date", "tickformat": "%d.%m."}, "yaxis": {"rangemode": "normal"}, "showlegend": False},
        Table(["Date", "EF", "km"], [list(p) for p in points]),
        empty=None if points else "No easy runs yet.",
        note="Speed (metres per minute) divided by heart rate. If you run faster at the same heart rate, "
        "or at a lower heart rate at the same pace, the value rises: your aerobic fitness is improving. "
        "Single runs vary with heat, hills and fatigue, so watch the trend over weeks.",
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
        "Nightly average and 7-day mean against the baseline range",
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
    pages = {
        "overview": [asdict(c) for c in dash.overview_charts],
        "plan": [asdict(c) for c in dash.plan_charts],
        "health": [asdict(c) for c in dash.health_charts],
    }
    return template.render(
        d=dash,
        pages=pages,
        charts=[{**c, "page": page} for page, charts in pages.items() for c in charts],
        plotly_js=PLOTLY_JS,
        types=TYPES,
    )


def build(ctx: tools.Context) -> str:
    return render(collect(ctx))
