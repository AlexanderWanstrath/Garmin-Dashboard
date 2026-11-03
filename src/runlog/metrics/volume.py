"""Weekly running volume, increase rate and long runs."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta

from runlog.metrics import Row, activity_date, is_run, mean, week_start


@dataclass
class Week:
    start: date
    km: float
    runs: int
    duration_s: float
    longest_km: float
    long_runs: int
    increase_vs_prev_pct: float | None  # (km - previous week) / previous week
    increase_vs_3wk_pct: float | None  # against the mean of the three previous weeks


def weekly_volume(activities: list[Row], long_run_min_km: float, until: date | None = None) -> list[Week]:
    """One entry per week from the first run to `until`, including weeks without runs."""
    runs = [a for a in activities if is_run(a)]
    if not runs:
        return []
    first = week_start(min(activity_date(a) for a in runs))
    last = week_start(until or max(activity_date(a) for a in runs))

    by_week: dict[date, list[Row]] = {}
    for a in runs:
        by_week.setdefault(week_start(activity_date(a)), []).append(a)

    weeks: list[Week] = []
    start = first
    while start <= last:
        items = by_week.get(start, [])
        km = [(a.get("distance_m") or 0) / 1000 for a in items]
        total = sum(km)
        prev = weeks[-1].km if weeks else None
        prev3 = [w.km for w in weeks[-3:]]
        weeks.append(
            Week(
                start=start,
                km=round(total, 2),
                runs=len(items),
                duration_s=sum(a.get("duration_s") or 0 for a in items),
                longest_km=round(max(km, default=0), 2),
                long_runs=sum(k >= long_run_min_km for k in km),
                increase_vs_prev_pct=increase_pct(total, prev),
                increase_vs_3wk_pct=increase_pct(total, mean(prev3)) if len(prev3) == 3 else None,
            )
        )
        start += timedelta(days=7)
    return weeks


def increase_pct(current: float, reference: float | None) -> float | None:
    if not reference:
        return None
    return round((current - reference) / reference * 100, 1)
