"""Weekly intensity distribution: share of time in easy zones vs. hard zones (target 80/20)."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date

from runlog.metrics import Row, activity_date, is_run, week_start


@dataclass
class IntensityWeek:
    start: date
    zone_s: dict[int, float]
    easy_s: float
    hard_s: float
    easy_pct: float | None


def weekly_intensity(activities: list[Row], easy_zones: Iterable[int]) -> list[IntensityWeek]:
    easy = set(easy_zones)
    weeks: dict[date, dict[int, float]] = {}
    for a in activities:
        if not is_run(a):
            continue
        zones = weeks.setdefault(week_start(activity_date(a)), dict.fromkeys(range(1, 6), 0.0))
        for i in range(1, 6):
            zones[i] += a.get(f"hr_zone_{i}_s") or 0

    result = []
    for start in sorted(weeks):
        zones = weeks[start]
        easy_s = sum(v for z, v in zones.items() if z in easy)
        hard_s = sum(v for z, v in zones.items() if z not in easy)
        total = easy_s + hard_s
        result.append(
            IntensityWeek(
                start=start,
                zone_s=zones,
                easy_s=easy_s,
                hard_s=hard_s,
                easy_pct=round(easy_s / total * 100, 1) if total else None,
            )
        )
    return result
