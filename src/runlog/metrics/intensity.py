"""Weekly intensity distribution: share of easy vs. hard time (target 80/20).

Two variants: by Garmin's per-run zone times, or by a fixed heart rate cap applied to the
per-second samples. The cap variant stays comparable when Garmin moves the zone limits.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass
from datetime import date

from runlog.metrics import Row, activity_date, is_run, week_start

MIN_SPEED = 0.5  # m/s; slower samples are standing and do not count


def hr_split(samples: list[Row], hr_cap: float) -> tuple[int, int]:
    """Moving seconds at or below the cap and above it (one sample per second)."""
    moving = [s["hr"] for s in samples if s.get("hr") and (s.get("speed") or 0) >= MIN_SPEED]
    above = sum(hr > hr_cap for hr in moving)
    return len(moving) - above, above


def share_above(samples: list[Row], hr_cap: float) -> float | None:
    below, above = hr_split(samples, hr_cap)
    return above / (below + above) if below + above else None


def weekly_intensity_by_hr(
    activities: list[Row], samples_for: Callable[[int], list[Row]], easy_hr_max: float
) -> list[IntensityWeek]:
    weeks: dict[date, list[int]] = {}
    for a in activities:
        if not is_run(a):
            continue
        below, above = hr_split(samples_for(a["id"]), easy_hr_max)
        totals = weeks.setdefault(week_start(activity_date(a)), [0, 0])
        totals[0] += below
        totals[1] += above
    return [
        IntensityWeek(
            start=start,
            zone_s={},
            easy_s=easy,
            hard_s=hard,
            easy_pct=round(easy / (easy + hard) * 100, 1) if easy + hard else None,
        )
        for start, (easy, hard) in sorted(weeks.items())
    ]


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
