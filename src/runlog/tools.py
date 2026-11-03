"""Read-only queries behind the MCP tools. Each returns compact JSON-ready data with units in
the field names. No access to Garmin, the API key or anything outside the database and config.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any

from runlog import data
from runlog.metrics import activity_date, is_run
from runlog.metrics.decoupling import decoupling_pct
from runlog.metrics.efficiency import efficiency_factor
from runlog.metrics.intensity import share_above, weekly_intensity, weekly_intensity_by_hr
from runlog.metrics.recovery import recovery
from runlog.metrics.volume import weekly_volume
from runlog.plan import TYPES, Plan, evaluate, format_pace, weekly_status
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
        "avg_hr_bpm": _round(a.get("avg_hr"), 0),
        "max_hr_bpm": _round(a.get("max_hr"), 0),
        f"time_above_{easy_cap}_bpm_pct": round(above * 100) if above is not None else None,
        "elevation_gain_m": _round(a.get("elevation_gain_m"), 0),
        "cadence_spm": _round(a.get("avg_cadence_spm"), 0),
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
            "status": r.status,
            "actual_date": r.actual_date.isoformat() if r.actual_date else None,
            "actual_km": r.actual_km,
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
