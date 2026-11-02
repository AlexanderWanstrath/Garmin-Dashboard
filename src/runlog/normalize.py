"""Turn Garmin JSON responses into table rows. Pure functions, no I/O."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

JSON = dict[str, Any]


def get(obj: Any, path: str) -> Any:
    """Nested lookup by dotted path; None if any step is missing."""
    for part in path.split("."):
        if not isinstance(obj, dict):
            return None
        obj = obj.get(part)
    return obj


def activity_row(summary: JSON, detail: JSON | None) -> JSON:
    """One activities row from the activity list entry, enriched by the detail view where it has more."""
    d = (detail or {}).get("summaryDTO") or {}

    def pick(detail_key: str, summary_key: str | None = None) -> Any:
        value = d.get(detail_key)
        return value if value is not None else summary.get(summary_key or detail_key)

    row = {
        "id": summary["activityId"],
        "source": "garmin",
        "start_time_local": summary.get("startTimeLocal"),
        "start_time_gmt": summary.get("startTimeGMT"),
        "type": get(summary, "activityType.typeKey"),
        "name": summary.get("activityName"),
        "distance_m": pick("distance"),
        "duration_s": pick("duration"),
        "elapsed_s": pick("elapsedDuration"),
        "moving_s": pick("movingDuration"),
        "avg_hr": pick("averageHR"),
        "max_hr": pick("maxHR"),
        "min_hr": d.get("minHR"),
        "avg_speed": pick("averageSpeed"),
        "max_speed": pick("maxSpeed"),
        "avg_moving_speed": d.get("averageMovingSpeed"),
        "avg_grade_adjusted_speed": pick("avgGradeAdjustedSpeed"),
        "elevation_gain_m": pick("elevationGain"),
        "elevation_loss_m": pick("elevationLoss"),
        "min_elevation_m": pick("minElevation"),
        "max_elevation_m": pick("maxElevation"),
        "avg_cadence_spm": pick("averageRunCadence", "averageRunningCadenceInStepsPerMinute"),
        "max_cadence_spm": pick("maxRunCadence", "maxRunningCadenceInStepsPerMinute"),
        "avg_power_w": pick("averagePower", "avgPower"),
        "max_power_w": pick("maxPower"),
        "norm_power_w": pick("normalizedPower", "normPower"),
        "total_work_j": d.get("totalWork"),
        "ground_contact_ms": pick("groundContactTime", "avgGroundContactTime"),
        "stride_length_cm": pick("strideLength", "avgStrideLength"),
        "vertical_oscillation_cm": pick("verticalOscillation", "avgVerticalOscillation"),
        "vertical_ratio_pct": pick("verticalRatio", "avgVerticalRatio"),
        "aerobic_te": pick("trainingEffect", "aerobicTrainingEffect"),
        "anaerobic_te": pick("anaerobicTrainingEffect"),
        "te_label": pick("trainingEffectLabel"),
        "garmin_rpe": d.get("directWorkoutRpe"),
        "garmin_feel": d.get("directWorkoutFeel"),
        "calories_kcal": pick("calories"),
        "bmr_calories_kcal": pick("bmrCalories"),
        "steps": pick("steps"),
        "body_battery_change": pick("differenceBodyBattery"),
        "moderate_minutes": pick("moderateIntensityMinutes"),
        "vigorous_minutes": pick("vigorousIntensityMinutes"),
        "min_temperature_c": pick("minTemperature"),
        "max_temperature_c": pick("maxTemperature"),
        "avg_temperature_c": d.get("averageTemperature"),
        "lap_count": summary.get("lapCount"),
        "fastest_1k_s": summary.get("fastestSplit_1000"),
        "fastest_mile_s": summary.get("fastestSplit_1609"),
        "fastest_5k_s": summary.get("fastestSplit_5000"),
        "fastest_10k_s": summary.get("fastestSplit_10000"),
    }
    for i in range(1, 6):
        row[f"hr_zone_{i}_s"] = summary.get(f"hrTimeInZone_{i}")
        row[f"power_zone_{i}_s"] = summary.get(f"powerTimeInZone_{i}")
    return row


def daily_summary_rows(response: Any) -> dict[str, JSON]:
    """Rows keyed by date from /usersummary-service/v2/dailysummaries (entries under "data")."""
    entries = response.get("data", []) if isinstance(response, dict) else response or []
    rows = {}
    for e in entries:
        if not isinstance(e, dict) or not e.get("calendarDate"):
            continue
        rows[e["calendarDate"]] = {
            "resting_hr": get(e, "heartRate.restingValue"),
            "min_hr": get(e, "heartRate.minValue"),
            "max_hr": get(e, "heartRate.maxValue"),
            "steps": get(e, "movement.steps.value"),
            "step_goal": get(e, "movement.steps.goal"),
            "steps_distance_m": get(e, "movement.steps.distanceInMeters"),
            "floors_up": get(e, "movement.floorsAscended.value"),
            "floors_down": get(e, "movement.floorsDescended.value"),
            "calories_total_kcal": get(e, "calories.burnedTotal"),
            "calories_active_kcal": get(e, "calories.burnedActive"),
            "calories_resting_kcal": get(e, "calories.burnedResting"),
            "moderate_minutes": get(e, "intensityMinutes.moderate"),
            "vigorous_minutes": get(e, "intensityMinutes.vigorous"),
            "intensity_goal_min": get(e, "intensityMinutes.goal"),
            "stress_avg": get(e, "stress.avgLevel"),
            "stress_max": get(e, "stress.maxLevel"),
            "stress_qualifier": get(e, "stress.qualifier"),
            "stress_rest_s": _ms_to_s(get(e, "stress.restDurationInMillis")),
            "stress_low_s": _ms_to_s(get(e, "stress.lowStressDurationInMillis")),
            "stress_medium_s": _ms_to_s(get(e, "stress.mediumStressDurationInMillis")),
            "stress_high_s": _ms_to_s(get(e, "stress.highStressDurationInMillis")),
            "stress_activity_s": _ms_to_s(get(e, "stress.activityDurationInMillis")),
            "body_battery_min": get(e, "bodyBattery.minValue"),
            "body_battery_max": get(e, "bodyBattery.maxValue"),
            "body_battery_charged": get(e, "bodyBattery.chargedValue"),
            "body_battery_drained": get(e, "bodyBattery.drainedValue"),
            "body_battery_latest": get(e, "bodyBattery.latestValue"),
            "respiration_avg": get(e, "respiration.avgValue"),
            "respiration_min": get(e, "respiration.minValue"),
            "respiration_max": get(e, "respiration.maxValue"),
        }
    return rows


def hrv_rows(response: Any) -> dict[str, JSON]:
    """Rows keyed by date from /hrv-service/hrv/daily/{start}/{end}."""
    entries = get(response, "hrvSummaries") or []
    return {
        e["calendarDate"]: {
            "hrv_avg_ms": e.get("lastNightAvg"),
            "hrv_5min_high_ms": e.get("lastNight5MinHigh"),
            "hrv_weekly_avg_ms": e.get("weeklyAvg"),
            "hrv_baseline_low_ms": get(e, "baseline.balancedLow"),
            "hrv_baseline_high_ms": get(e, "baseline.balancedUpper"),
            "hrv_status": e.get("status"),
        }
        for e in entries
        if isinstance(e, dict) and e.get("calendarDate")
    }


def sleep_rows(response: Any) -> dict[str, JSON]:
    """Rows keyed by date (the morning the night ends) from dailySleepSummariesByDate."""
    entries = response if isinstance(response, list) else []
    rows = {}
    for e in entries:
        if not isinstance(e, dict) or not e.get("calendarDate") or not e.get("sleepTimeSeconds"):
            continue
        rows[e["calendarDate"]] = {
            "sleep_start_local": _local_ms_to_iso(e.get("sleepStartTimestampLocal")),
            "sleep_end_local": _local_ms_to_iso(e.get("sleepEndTimestampLocal")),
            "sleep_s": e.get("sleepTimeSeconds"),
            "deep_s": e.get("deepSleepSeconds"),
            "light_s": e.get("lightSleepSeconds"),
            "rem_s": e.get("remSleepSeconds"),
            "awake_s": e.get("awakeSleepSeconds"),
            "nap_s": e.get("napTimeSeconds"),
            "unmeasurable_s": e.get("unmeasurableSleepSeconds"),
            "awake_count": e.get("awakeCount"),
            "sleep_score": get(e, "sleepScores.overall.value"),
            "sleep_score_quality": get(e, "sleepScores.overall.qualifierKey"),
            "sleep_need_min": get(e, "sleepNeed.actual"),
            "sleep_avg_hr": e.get("avgHeartRate"),
            "sleep_avg_stress": e.get("avgSleepStress"),
            "sleep_respiration_avg": e.get("averageRespirationValue"),
            "sleep_respiration_min": e.get("lowestRespirationValue"),
            "sleep_respiration_max": e.get("highestRespirationValue"),
        }
    return rows


def merge_daily(*parts: dict[str, JSON]) -> dict[str, JSON]:
    """Combine per-date rows from several endpoints into one row per date."""
    merged: dict[str, JSON] = {}
    for part in parts:
        for day, row in part.items():
            merged.setdefault(day, {}).update(row)
    return merged


def _ms_to_s(value: Any) -> float | None:
    return value / 1000 if isinstance(value, int | float) else None


def _local_ms_to_iso(value: Any) -> str | None:
    """Garmin's *Local epoch milliseconds are local wall-clock time encoded as if UTC."""
    if not isinstance(value, int | float):
        return None
    return datetime.fromtimestamp(value / 1000, tz=UTC).replace(tzinfo=None).isoformat(timespec="minutes")
