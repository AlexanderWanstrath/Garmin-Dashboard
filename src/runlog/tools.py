"""Read-only queries behind the MCP tools. Each returns compact JSON-ready data with units in
the field names. No access to Garmin, the API key or anything outside the database and config.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any

from runlog import data
from runlog.metrics import activity_date, is_run, week_start
from runlog.metrics.decoupling import decoupling_pct
from runlog.metrics.efficiency import efficiency_factor
from runlog.metrics.intensity import share_above, weekly_intensity, weekly_intensity_by_hr, zone_split
from runlog.metrics.recovery import recovery
from runlog.metrics.volume import weekly_volume
from runlog.plan import (
    TYPES,
    Plan,
    describe_actual,
    describe_target,
    evaluate,
    format_pace,
    planned_km,
    weekly_status,
)
from runlog.warnings import morning_check, volume_warnings


@dataclass
class Context:
    conn: sqlite3.Connection
    config: dict[str, Any]
    plan: Plan | None
    today: date

    def cfg(self, section: str, key: str, default: Any) -> Any:
        return (self.config.get(section) or {}).get(key, default)


def _pace(speed: float | None) -> str | None:
    return format_pace(1000 / speed) if speed and speed > 0 else None


def _round(value: Any, digits: int = 1) -> Any:
    return round(value, digits) if isinstance(value, float) else value


def _int(value: Any) -> int | None:
    return round(value) if isinstance(value, int | float) else None


def _evaluate(ctx: Context, activities: list[dict[str, Any]]):
    return evaluate(
        ctx.plan,
        activities,
        ctx.today,
        samples_for=lambda i: data.samples(ctx.conn, i),
        laps_for=lambda i: data.laps(ctx.conn, i),
        fuel_for=lambda i: data.fuel_g(ctx.conn, i),
        over_cap_share=ctx.cfg("warnings", "easy_hr_over_cap_share", 0.1),
        rep_tolerance_s=ctx.cfg("warnings", "rep_pace_tolerance_s", 2),
    )


def _activities(ctx: Context) -> list[dict[str, Any]]:
    return [a for a in data.activities(ctx.conn) if activity_date(a) <= ctx.today]


def _run_summary(ctx: Context, a: dict[str, Any]) -> dict[str, Any]:
    easy_cap = ctx.cfg("intensity", "easy_hr_max", 140)
    above = share_above(data.samples(ctx.conn, a["id"]), easy_cap)
    rpe = a.get("garmin_rpe")
    return {
        "activity_id": a["id"],
        "date": a["start_time_local"][:10],
        "type": a.get("type"),
        "name": a.get("name"),
        "distance_km": _round((a.get("distance_m") or 0) / 1000, 2),
        "duration_min": _round((a.get("duration_s") or 0) / 60),
        "pace_min_per_km": _pace(a.get("avg_moving_speed") or a.get("avg_speed")),
        "avg_hr_bpm": _int(a.get("avg_hr")),
        "max_hr_bpm": _int(a.get("max_hr")),
        f"time_above_{easy_cap}_bpm_pct": round(above * 100) if above is not None else None,
        "elevation_gain_m": _int(a.get("elevation_gain_m")),
        "cadence_spm": _int(a.get("avg_cadence_spm")),
        "aerobic_training_effect": _round(a.get("aerobic_te")),
        "anaerobic_training_effect": _round(a.get("anaerobic_te")),
        "garmin_rpe_1_to_10": rpe / 10 if rpe is not None else None,
        "vo2max": a.get("vo2max"),
    }


def get_recent_runs(ctx: Context, days: int = 14) -> list[dict[str, Any]]:
    since = ctx.today - timedelta(days=days - 1)
    return [_run_summary(ctx, a) for a in _activities(ctx) if is_run(a) and activity_date(a) >= since]


def get_run_details(ctx: Context, activity_id: int) -> dict[str, Any]:
    a = next((x for x in data.activities(ctx.conn) if x["id"] == activity_id), None)
    if a is None:
        return {"error": f"no activity with id {activity_id}"}
    samples = data.samples(ctx.conn, activity_id)
    warmup_s = ctx.cfg("metrics", "decoupling_warmup_min", 10) * 60
    laps = [
        {
            "lap": lap["lap_index"] + 1,
            "intensity": lap.get("intensity"),
            "distance_km": _round((lap.get("distance_m") or 0) / 1000, 2),
            "time_min": _round((lap.get("timer_s") or 0) / 60, 2),
            "pace_min_per_km": _pace(lap.get("avg_speed")),
            "avg_hr_bpm": lap.get("avg_hr"),
            "max_hr_bpm": lap.get("max_hr"),
            "cadence_spm": _round(lap.get("avg_cadence_spm"), 0),
        }
        for lap in data.laps(ctx.conn, activity_id)
    ]
    details = {
        **_run_summary(ctx, a),
        "moving_min": _round((a.get("moving_s") or 0) / 60),
        "aerobic_decoupling_pct": decoupling_pct(samples, warmup_s) if is_run(a) else None,
        "efficiency_factor_m_per_min_per_bpm": efficiency_factor(a),
        "hr_zones_garmin_min": {f"z{i}": _round((a.get(f"hr_zone_{i}_s") or 0) / 60) for i in range(1, 6)},
        "fuel_g": data.fuel_g(ctx.conn, activity_id),
        "laps": laps,
    }
    long_cap = ctx.cfg("intensity", "long_hr_max", 145)
    above_long = share_above(samples, long_cap)
    details[f"time_above_{long_cap}_bpm_pct"] = round(above_long * 100) if above_long is not None else None
    if ctx.plan:
        match = next((r for r in _evaluate(ctx, _activities(ctx)) if r.activity_id == activity_id), None)
        if match:
            details["plan"] = {
                "session": match.session.name,
                "type": TYPES[match.session.type],
                "planned_date": match.session.date.isoformat(),
                "findings": match.findings,
            }
    return details


def get_weekly_volume(ctx: Context, weeks: int = 8) -> list[dict[str, Any]]:
    long_km = ctx.cfg("metrics", "long_run_min_km", 14)
    result = weekly_volume(_activities(ctx), long_km, until=ctx.today)[-weeks:]
    return [
        {
            "week_start": w.start.isoformat(),
            "distance_km": w.km,
            "runs": w.runs,
            "duration_h": _round(w.duration_s / 3600, 2),
            "longest_run_km": w.longest_km,
            "long_runs": w.long_runs,
            "change_vs_prev_week_pct": w.increase_vs_prev_pct,
            "change_vs_3_week_mean_pct": w.increase_vs_3wk_pct,
            "in_progress": w.start + timedelta(days=7) > ctx.today,
        }
        for w in result
    ]


def get_intensity_distribution(ctx: Context, weeks: int = 4) -> list[dict[str, Any]]:
    """Easy share by the fixed heart rate cap (main figure) and by Garmin's zones for comparison."""
    activities = _activities(ctx)
    cap = ctx.cfg("intensity", "easy_hr_max", 140)
    by_hr = weekly_intensity_by_hr(activities, lambda i: data.samples(ctx.conn, i), cap)[-weeks:]
    by_zone = {w.start: w for w in weekly_intensity(activities, ctx.cfg("metrics", "easy_zones", [1, 2]))}
    return [
        {
            "week_start": w.start.isoformat(),
            f"easy_below_{cap}_bpm_pct": w.easy_pct,
            "easy_min": round(w.easy_s / 60),
            "hard_min": round(w.hard_s / 60),
            "easy_by_garmin_zones_pct": by_zone[w.start].easy_pct if w.start in by_zone else None,
            "target_easy_pct": 80,
        }
        for w in by_hr
    ]


def get_recovery_status(ctx: Context, days: int = 14) -> list[dict[str, Any]]:
    daily = [d for d in data.daily_health(ctx.conn) if d["date"] <= ctx.today.isoformat()]
    by_date = {d["date"]: d for d in daily}
    hrv_range = ctx.cfg("baselines", "hrv_ms", None)
    rows = recovery(
        daily,
        hrv_range=(hrv_range["low"], hrv_range["high"]) if hrv_range else None,
        resting_hr_baseline=ctx.cfg("baselines", "resting_hr_bpm", None),
    )[-days:]
    result = []
    for r in rows:
        d = by_date.get(r.date.isoformat(), {})
        result.append(
            {
                "date": r.date.isoformat(),
                "hrv_ms": r.hrv_ms,
                "hrv_7d_ms": r.hrv_7d_ms,
                "hrv_baseline_ms": [r.hrv_low_ms, r.hrv_high_ms],
                "hrv_7d_vs_baseline": r.hrv_vs_baseline,
                "resting_hr_bpm": r.resting_hr,
                "resting_hr_7d_bpm": r.resting_hr_7d,
                "resting_hr_vs_baseline_bpm": r.resting_hr_delta,
                "sleep_h": _round((d.get("sleep_s") or 0) / 3600, 2) if d.get("sleep_s") else None,
                "sleep_score": d.get("sleep_score"),
                "deep_sleep_min": round(d["deep_s"] / 60) if d.get("deep_s") else None,
                "rem_sleep_min": round(d["rem_s"] / 60) if d.get("rem_s") else None,
                "body_battery_max": d.get("body_battery_max"),
                "stress_avg": d.get("stress_avg"),
                "steps": d.get("steps"),
            }
        )
    return result


def get_warnings(ctx: Context) -> dict[str, Any]:
    check = morning_check(ctx.today, data.daily_health(ctx.conn), data.manual_entries(ctx.conn), ctx.config)
    activities = _activities(ctx)
    weeks = weekly_volume(activities, ctx.cfg("metrics", "long_run_min_km", 14), until=ctx.today)
    result: dict[str, Any] = {
        "morning_check": {
            "date": check.date.isoformat(),
            "level": check.level,
            "advice": check.advice,
            "signals": [{"signal": s.name, "level": s.level, "reason": s.reason} for s in check.signals],
        },
        "training": [w.reason for w in volume_warnings(weeks, ctx.cfg("warnings", "weekly_volume_increase_pct", 10))],
    }
    if ctx.plan:
        recent = ctx.today - timedelta(days=7)
        result["plan_deviations_last_7_days"] = [
            {"date": r.session.date.isoformat(), "session": r.session.name, "status": r.status, "findings": r.findings}
            for r in _evaluate(ctx, activities)
            if recent <= r.session.date <= ctx.today and (r.findings or r.status == "missed")
        ]
    return result


def get_plan_status(ctx: Context, days_back: int = 7, days_ahead: int = 7) -> dict[str, Any]:
    if not ctx.plan:
        return {"error": "no training plan (plan.yaml) configured"}
    activities = _activities(ctx)
    start, end = ctx.today - timedelta(days=days_back), ctx.today + timedelta(days=days_ahead)
    sessions = [
        {
            "date": r.session.date.isoformat(),
            "type": TYPES[r.session.type],
            "session": r.session.name,
            "planned_km": list(r.session.km) if r.session.km else None,
            "target": describe_target(r.session),
            "status": r.status,
            "actual_date": r.actual_date.isoformat() if r.actual_date else None,
            "actual_km": r.actual_km,
            "actual": describe_actual(r),
            "activity_ids": r.activity_ids,
            "findings": r.findings,
        }
        for r in _evaluate(ctx, activities)
        if start <= r.session.date <= end
    ]
    weeks = [
        {
            "week_start": w.week.start.isoformat(),
            "label": w.week.label,
            "planned_km": list(w.week.km),
            "actual_km": w.actual_km,
            "status": w.status,
        }
        for w in weekly_status(ctx.plan, activities, ctx.today)[-3:]
    ]
    return {"sessions": sessions, "weeks": weeks}


DEFAULT_ZONES = [{"name": "Easy", "max_bpm": 140}, {"name": "Moderate", "max_bpm": 160}, {"name": "Hard"}]


def zones(ctx: Context) -> list[dict[str, Any]]:
    """Heart rate zones from the config (intensity.zones); the first one ends at the easy cap by default."""
    configured = ctx.cfg("intensity", "zones", None)
    if configured:
        return configured
    easy_cap = ctx.cfg("intensity", "easy_hr_max", 140)
    return [{**DEFAULT_ZONES[0], "max_bpm": easy_cap}, *DEFAULT_ZONES[1:]]


def zone_labels(zone_list: list[dict[str, Any]]) -> list[str]:
    """'Easy ≤ 140', 'Moderate 141–160', 'Hard > 160'."""
    labels = []
    for i, zone in enumerate(zone_list):
        previous = zone_list[i - 1] if i else None
        if "max_bpm" not in zone:
            labels.append(f"{zone['name']} > {previous['max_bpm']:g}" if previous else zone["name"])
        elif previous:
            labels.append(f"{zone['name']} {previous['max_bpm'] + 1:g}–{zone['max_bpm']:g}")
        else:
            labels.append(f"{zone['name']} ≤ {zone['max_bpm']:g}")
    return labels


def get_zone_volume(ctx: Context, weeks: int = 8) -> list[dict[str, Any]]:
    """Running km and minutes per heart rate zone and week, from the per-second samples.

    Zone km are scaled to the run's recorded distance, so they add up to the weekly km.
    """
    zone_list = zones(ctx)
    bounds = [z["max_bpm"] for z in zone_list[:-1]]
    names = [z["name"].lower() for z in zone_list]
    by_week: dict[date, dict[str, list[float]]] = {}
    for a in _activities(ctx):
        if not is_run(a):
            continue
        metres, seconds = zone_split(data.samples(ctx.conn, a["id"]), bounds)
        total = sum(metres)
        scale = (a.get("distance_m") or 0) / total if total else 0
        week = by_week.setdefault(week_start(activity_date(a)), {"km": [0.0] * len(names), "min": [0.0] * len(names)})
        for i in range(len(names)):
            week["km"][i] += metres[i] * scale / 1000
            week["min"][i] += seconds[i] / 60
    result = []
    for start in sorted(by_week)[-weeks:]:
        week = by_week[start]
        result.append(
            {
                "week_start": start.isoformat(),
                **{f"{n}_km": round(km, 1) for n, km in zip(names, week["km"], strict=True)},
                **{f"{n}_min": round(m) for n, m in zip(names, week["min"], strict=True)},
            }
        )
    return result


def get_plan_progress(ctx: Context) -> dict[str, Any]:
    """Km planned up to today against km run since the plan started, in total and per plan week,
    with the run km split into heart rate zones."""
    if not ctx.plan or not ctx.plan.sessions:
        return {"error": "no training plan (plan.yaml) configured"}
    results = _evaluate(ctx, _activities(ctx))
    # Today's session counts as planned once it is done; until then it may still be run.
    planned = sum(planned_km(r.session) for r in results if r.session.date < ctx.today or r.activity_id is not None)
    plan_start = week_start(ctx.plan.sessions[0].date)
    names = [z["name"].lower() for z in zones(ctx)]
    zone_weeks = {w["week_start"]: w for w in get_zone_volume(ctx, weeks=520) if w["week_start"] >= str(plan_start)}
    plan_weeks = {w.start: w for w in ctx.plan.weeks}
    weeks = []
    # Weeks without a weekly target in plan.yaml still show up with the sum of their sessions.
    for start in sorted(set(plan_weeks) | {week_start(s.date) for s in ctx.plan.sessions}):
        sessions_km = round(sum(planned_km(s) for s in ctx.plan.sessions if week_start(s.date) == start), 1)
        w = plan_weeks.get(start)
        zw = zone_weeks.get(start.isoformat(), {})
        weeks.append(
            {
                "week_start": start.isoformat(),
                "label": w.label if w else None,
                "planned_km": list(w.km) if w else [sessions_km, sessions_km],
                "sessions_km": sessions_km,
                "done_km": round(sum(zw.get(f"{n}_km", 0) for n in names), 1),
                **{f"{n}_km": zw.get(f"{n}_km", 0) for n in names},
                "future": start > ctx.today,
            }
        )
    done = {n: round(sum(w.get(f"{n}_km", 0) for w in zone_weeks.values()), 1) for n in names}
    return {
        "plan_start": plan_start.isoformat(),
        "planned_km_to_date": round(planned, 1),
        "done_km": round(sum(done.values()), 1),
        "done_by_zone_km": done,
        "planned_km_total": round(sum(planned_km(s) for s in ctx.plan.sessions), 1),
        "zones": zone_labels(zones(ctx)),
        "weeks": weeks,
    }


def get_countdown(ctx: Context) -> list[dict[str, Any]]:
    events = []
    for e in ctx.config.get("events") or []:
        day = e["date"] if isinstance(e["date"], date) else date.fromisoformat(str(e["date"]))
        if day >= ctx.today:
            events.append(
                {"event": e["name"], "date": day.isoformat(), "goal": e.get("goal"), "days": (day - ctx.today).days}
            )
    if not events and ctx.plan:
        events = [
            {"event": s.name, "date": s.date.isoformat(), "goal": None, "days": (s.date - ctx.today).days}
            for s in ctx.plan.sessions
            if s.type == "R" and s.date >= ctx.today
        ]
    return sorted(events, key=lambda e: e["date"])


def get_manual_entries(ctx: Context, days: int = 14) -> list[dict[str, Any]]:
    since = (ctx.today - timedelta(days=days - 1)).isoformat()
    return [
        {
            "date": m["date"],
            "patellar_tendon_0_to_10": m.get("tendon_pain"),
            "startup_pain": bool(m["startup_pain"]) if m.get("startup_pain") is not None else None,
            "legs": m.get("legs"),
            "hip_pain": bool(m["hip_pain"]) if m.get("hip_pain") is not None else None,
            "fuel_g": m.get("fuel_g"),
            "activity_id": m.get("activity_id"),
            "note": m.get("note"),
        }
        for m in data.manual_entries(ctx.conn)
        if since <= m["date"] <= ctx.today.isoformat()
    ]
