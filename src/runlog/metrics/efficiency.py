"""Efficiency factor of easy runs: speed (m/min) per heartbeat. Rising = fitter."""

from __future__ import annotations

from collections.abc import Iterable

from runlog.metrics import Row, is_run

EASY_SHARE = 0.8  # a run counts as easy if at least this share of zone time is in the easy zones
# Outside this range the recording is broken (e.g. track mode losing distance), not the runner.
PLAUSIBLE_SPEED = (1.0, 7.0)  # m/s, about 16:40 to 2:23 min/km


def easy_share(activity: Row, easy_zones: Iterable[int]) -> float | None:
    zones = {i: activity.get(f"hr_zone_{i}_s") or 0 for i in range(1, 6)}
    total = sum(zones.values())
    if not total:
        return None
    return sum(zones[z] for z in easy_zones) / total


def is_easy_run(activity: Row, easy_zones: Iterable[int]) -> bool:
    share = easy_share(activity, easy_zones)
    return is_run(activity) and share is not None and share >= EASY_SHARE


def efficiency_factor(activity: Row) -> float | None:
    """Average moving speed in m/min divided by average heart rate."""
    speed = activity.get("avg_moving_speed") or activity.get("avg_speed")
    hr = activity.get("avg_hr")
    if not speed or not hr or not PLAUSIBLE_SPEED[0] <= speed <= PLAUSIBLE_SPEED[1]:
        return None
    return round(speed * 60 / hr, 3)
