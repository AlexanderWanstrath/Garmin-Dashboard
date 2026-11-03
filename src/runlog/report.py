"""Text report for `runlog check`: morning check, warnings and plan comparison."""

from __future__ import annotations

import sqlite3
from datetime import date, timedelta
from typing import Any

from runlog import data
from runlog.metrics.volume import weekly_volume
from runlog.plan import TYPES, Plan, evaluate, weekly_status
from runlog.warnings import morning_check, volume_warnings

PLAN_LOOKBACK_DAYS = 7
PLAN_LOOKAHEAD_DAYS = 3


def build_report(conn: sqlite3.Connection, cfg: dict[str, Any], plan: Plan | None, today: date) -> str:
    # Only what was known on `today`, so a report for a past date is reproducible.
    activities = [a for a in data.activities(conn) if a["start_time_local"][:10] <= today.isoformat()]
    manual = data.manual_entries(conn)
    lines: list[str] = []

    check = morning_check(today, data.daily_health(conn), manual, cfg)
    lines.append(f"Morning check {today:%a %d.%m.}: {(check.level or 'no data').upper()}")
    for s in check.signals:
        lines.append(f"  {s.name:<11} {s.level or '-':<7} {s.reason}")
    if check.advice:
        lines.append(f"  -> {check.advice}")
    if any(s.level is None and s.name in ("tendon", "legs") for s in check.signals):
        lines.append("  (log with: runlog log --tendon 1 --legs fresh)")
    hip = [m for m in manual if m["date"] == today.isoformat() and m.get("hip_pain")]
    if hip:
        lines.append("  Hip pain logged today: skip quality and long runs per plan rules.")

    warnings_cfg = cfg.get("warnings") or {}
    long_run_km = (cfg.get("metrics") or {}).get("long_run_min_km", 14)
    weeks = weekly_volume(activities, long_run_km, until=today)
    warnings = volume_warnings(weeks, warnings_cfg.get("weekly_volume_increase_pct", 10))
    lines.append("")
    lines.append("Warnings" if warnings else "Warnings: none")
    lines += [f"  - {w.reason}" for w in warnings]

    if plan is None:
        lines += ["", "Plan: no plan.yaml (copy plan.example.yaml to compare runs with your plan)"]
        return "\n".join(lines)

    results = evaluate(
        plan,
        activities,
        today,
        samples_for=lambda i: data.samples(conn, i),
        laps_for=lambda i: data.laps(conn, i),
        fuel_for=lambda i: data.fuel_g(conn, i),
        over_cap_share=warnings_cfg.get("easy_hr_over_cap_share", 0.1),
        rep_tolerance_s=warnings_cfg.get("rep_pace_tolerance_s", 2),
    )
    window = [
        r
        for r in results
        if today - timedelta(days=PLAN_LOOKBACK_DAYS) <= r.session.date <= today + timedelta(days=PLAN_LOOKAHEAD_DAYS)
    ]
    lines += ["", "Plan"]
    if not window:
        lines.append("  no sessions planned around today")
    for r in window:
        s = r.session
        km = f"{r.actual_km:g} km" if r.actual_km is not None else ""
        moved = f" on {r.actual_date:%a %d.%m.}" if r.status == "moved" else ""
        verdict = "as planned" if r.status in ("done", "moved") and not r.findings else ""
        lines.append(f"  {s.date:%a %d.%m.} {s.type} {s.name:<34} {r.status}{moved} {km} {verdict}".rstrip())
        lines += [f"      ! {f}" for f in r.findings]

    for w in weekly_status(plan, activities, today)[-2:]:
        low, high = w.week.km
        planned = f"{low:g}" if low == high else f"{low:g}-{high:g}"
        label = f" ({w.week.label})" if w.week.label else ""
        lines.append(f"  Week of {w.week.start:%d.%m.}{label}: {w.actual_km:g} of {planned} km, {w.status}")

    missed = [r for r in results if r.status == "missed"]
    if missed:
        types = ", ".join(sorted({TYPES[r.session.type] for r in missed}))
        lines.append(f"  Missed so far: {len(missed)} session(s) ({types})")
    return "\n".join(lines)
