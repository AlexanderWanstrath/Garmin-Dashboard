"""Morning check (traffic light per signal) and training warnings, each with a reason."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any

from runlog.metrics import Row
from runlog.metrics.volume import Week

LEVELS = ["green", "yellow", "red"]
LEGS = {"fresh": "green", "heavy": "yellow", "very_heavy": "red"}

DEFAULT_CHECK = {
    "tendon": {"yellow": 2, "red": 4},
    "hrv_ms": {"low": 85, "red_days": 2},
    "resting_hr_bpm": {"yellow": 43, "red": 46, "red_days": 2},
    "advice": {
        "green": "Train as planned.",
        "yellow": "Long run 20-30 % shorter, quality session becomes an easy run.",
        "red": "Easy or rest day, rethink the plan.",
    },
}


@dataclass
class Signal:
    name: str
    level: str | None  # green, yellow, red; None = no data
    reason: str


@dataclass
class MorningCheck:
    date: date
    signals: list[Signal]
    level: str | None
    advice: str | None


@dataclass
class TrainingWarning:
    kind: str
    reason: str


def morning_check(day: date, daily: list[Row], manual: list[Row], config: dict[str, Any] | None = None) -> MorningCheck:
    cfg = {**DEFAULT_CHECK, **((config or {}).get("morning_check") or {})}
    by_date = {str(d["date"]): d for d in daily}
    entry = latest_entry(manual, day)
    signals = [
        tendon_signal(entry, cfg["tendon"]),
        hrv_signal(day, by_date, cfg["hrv_ms"]),
        resting_hr_signal(day, by_date, cfg["resting_hr_bpm"]),
        legs_signal(entry),
    ]
    known = [s.level for s in signals if s.level]
    level = max(known, key=LEVELS.index) if known else None
    return MorningCheck(day, signals, level, (cfg.get("advice") or {}).get(level) if level else None)


def latest_entry(manual: list[Row], day: date) -> Row | None:
    """Latest morning-check entry of the day (entries with tendon or legs set)."""
    entries = [
        m for m in manual if str(m["date"]) == day.isoformat() and (m.get("tendon_pain") is not None or m.get("legs"))
    ]
    return max(entries, key=lambda m: (str(m.get("created_at")), m.get("id") or 0)) if entries else None


def tendon_signal(entry: Row | None, cfg: dict[str, Any]) -> Signal:
    if entry is None or entry.get("tendon_pain") is None:
        return Signal("tendon", None, "not logged today")
    pain = entry["tendon_pain"]
    if entry.get("startup_pain"):
        return Signal("tendon", "red", f"{pain}/10 with pain when starting to move")
    if pain >= cfg["red"]:
        return Signal("tendon", "red", f"{pain}/10 (red from {cfg['red']})")
    if pain >= cfg["yellow"]:
        return Signal("tendon", "yellow", f"{pain}/10 (yellow from {cfg['yellow']})")
    return Signal("tendon", "green", f"{pain}/10")


def hrv_signal(day: date, by_date: dict[str, Row], cfg: dict[str, Any]) -> Signal:
    value = (by_date.get(day.isoformat()) or {}).get("hrv_avg_ms")
    if value is None:
        return Signal("hrv", None, "no HRV for last night")
    low = cfg["low"]
    if value >= low:
        return Signal("hrv", "green", f"{value} ms")
    days = consecutive(day, by_date, lambda r: r.get("hrv_avg_ms") is not None and r["hrv_avg_ms"] < low)
    if days >= cfg["red_days"]:
        return Signal("hrv", "red", f"{value} ms, {days} nights in a row below {low}")
    return Signal("hrv", "yellow", f"{value} ms, below {low}")


def resting_hr_signal(day: date, by_date: dict[str, Row], cfg: dict[str, Any]) -> Signal:
    value = (by_date.get(day.isoformat()) or {}).get("resting_hr")
    if value is None:
        return Signal("resting_hr", None, "no resting heart rate yet")
    if value >= cfg["red"]:
        days = consecutive(day, by_date, lambda r: r.get("resting_hr") is not None and r["resting_hr"] >= cfg["red"])
        if days >= cfg["red_days"]:
            return Signal("resting_hr", "red", f"{value} bpm, {days} days in a row at {cfg['red']} or above")
        return Signal("resting_hr", "yellow", f"{value} bpm, first day at {cfg['red']} or above")
    if value >= cfg["yellow"]:
        return Signal("resting_hr", "yellow", f"{value} bpm (yellow from {cfg['yellow']})")
    return Signal("resting_hr", "green", f"{value} bpm")


def legs_signal(entry: Row | None) -> Signal:
    legs = (entry or {}).get("legs")
    if not legs:
        return Signal("legs", None, "not logged today")
    return Signal("legs", LEGS.get(legs), legs.replace("_", " "))


def consecutive(day: date, by_date: dict[str, Row], condition: Any) -> int:
    """Number of days up to and including `day` in a row where condition holds."""
    count = 0
    while condition(by_date.get((day - timedelta(days=count)).isoformat()) or {}):
        count += 1
    return count


def volume_warnings(weeks: list[Week], max_increase_pct: float) -> list[TrainingWarning]:
    """Weekly km rising faster than allowed against the mean of the three previous weeks."""
    warnings = []
    for week in weeks[-2:]:  # last completed week and the current one
        if week.increase_vs_3wk_pct is not None and week.increase_vs_3wk_pct > max_increase_pct:
            warnings.append(
                TrainingWarning(
                    "volume",
                    f"week of {week.start}: {week.km:.1f} km is {week.increase_vs_3wk_pct:+.0f} % against the "
                    f"3-week mean (limit {max_increase_pct:+.0f} %)",
                )
            )
    return warnings
