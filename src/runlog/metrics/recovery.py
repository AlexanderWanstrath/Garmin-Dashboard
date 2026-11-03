"""HRV and resting heart rate against the personal baseline.

HRV baseline: Garmin's own balanced range per night if present, else the range from config.
Resting HR baseline: from config if set, else the median of the previous 28 days.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from statistics import median

from runlog.metrics import Row, mean

ROLLING_DAYS = 7
RHR_BASELINE_DAYS = 28
RHR_BASELINE_MIN_DAYS = 14


@dataclass
class RecoveryDay:
    date: date
    hrv_ms: int | None
    hrv_7d_ms: float | None
    hrv_low_ms: float | None
    hrv_high_ms: float | None
    hrv_vs_baseline: str | None  # "below", "within", "above"
    resting_hr: int | None
    resting_hr_7d: float | None
    resting_hr_baseline: float | None
    resting_hr_delta: float | None  # today minus baseline


def recovery(
    daily: list[Row],
    hrv_range: tuple[float, float] | None = None,
    resting_hr_baseline: float | None = None,
) -> list[RecoveryDay]:
    by_date = {date.fromisoformat(str(d["date"])): d for d in daily}
    result = []
    for day in sorted(by_date):
        row = by_date[day]
        window = [by_date.get(day - timedelta(days=i)) or {} for i in range(ROLLING_DAYS)]
        hrv_7d = mean([w.get("hrv_avg_ms") for w in window])
        rhr_7d = mean([w.get("resting_hr") for w in window])

        low, high = row.get("hrv_baseline_low_ms"), row.get("hrv_baseline_high_ms")
        if (low is None or high is None) and hrv_range:
            low, high = hrv_range

        rhr_base = resting_hr_baseline
        if rhr_base is None:
            history = [
                (by_date.get(day - timedelta(days=i)) or {}).get("resting_hr") for i in range(1, RHR_BASELINE_DAYS + 1)
            ]
            history = [h for h in history if h is not None]
            rhr_base = median(history) if len(history) >= RHR_BASELINE_MIN_DAYS else None

        rhr = row.get("resting_hr")
        result.append(
            RecoveryDay(
                date=day,
                hrv_ms=row.get("hrv_avg_ms"),
                hrv_7d_ms=round(hrv_7d, 1) if hrv_7d is not None else None,
                hrv_low_ms=low,
                hrv_high_ms=high,
                hrv_vs_baseline=classify(hrv_7d, low, high),
                resting_hr=rhr,
                resting_hr_7d=round(rhr_7d, 1) if rhr_7d is not None else None,
                resting_hr_baseline=rhr_base,
                resting_hr_delta=round(rhr - rhr_base, 1) if rhr is not None and rhr_base is not None else None,
            )
        )
    return result


def classify(value: float | None, low: float | None, high: float | None) -> str | None:
    if value is None or low is None or high is None:
        return None
    if value < low:
        return "below"
    if value > high:
        return "above"
    return "within"
