"""Training metrics. Pure functions over plain rows; loading from the database lives in runlog.data."""

from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Any

Row = dict[str, Any]


def is_run(activity: Row) -> bool:
    """running, track_running, trail_running, treadmill_running, ..."""
    return "running" in (activity.get("type") or "")


def activity_date(activity: Row) -> date:
    return datetime.fromisoformat(str(activity["start_time_local"])).date()


def week_start(day: date) -> date:
    """Monday of the ISO week."""
    return day - timedelta(days=day.weekday())


def mean(values: list[float]) -> float | None:
    values = [v for v in values if v is not None]
    return sum(values) / len(values) if values else None
