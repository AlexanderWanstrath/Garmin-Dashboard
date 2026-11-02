from runlog import normalize

SUMMARY = {
    "activityId": 1,
    "activityName": "Morning Run",
    "startTimeLocal": "2026-01-01 08:00:00",
    "activityType": {"typeKey": "running"},
    "distance": 10000.0,
    "averageHR": 150.0,
    "averageRunningCadenceInStepsPerMinute": 170.0,
    "hrTimeInZone_2": 1200.0,
    "fastestSplit_5000": 1500.0,
}


def test_activity_row_from_summary_only():
    row = normalize.activity_row(SUMMARY, None)
    assert row["id"] == 1
    assert row["type"] == "running"
    assert row["distance_m"] == 10000.0
    assert row["avg_cadence_spm"] == 170.0
    assert row["hr_zone_2_s"] == 1200.0
    assert row["hr_zone_1_s"] is None
    assert row["fastest_5k_s"] == 1500.0
    assert row["min_hr"] is None


def test_detail_takes_precedence_and_adds_fields():
    detail = {"summaryDTO": {"averageHR": 151.0, "minHR": 90.0, "directWorkoutRpe": 50}}
    row = normalize.activity_row(SUMMARY, detail)
    assert row["avg_hr"] == 151.0
    assert row["min_hr"] == 90.0
    assert row["garmin_rpe"] == 50
    assert row["distance_m"] == 10000.0  # falls back to the summary


def test_daily_summary_rows():
    response = {
        "data": [
            {
                "calendarDate": "2026-01-01",
                "heartRate": {"restingValue": 48},
                "movement": {"steps": {"value": 12000, "goal": 10000}},
                "stress": {"avgLevel": 25, "highStressDurationInMillis": 60000},
            }
        ]
    }
    row = normalize.daily_summary_rows(response)["2026-01-01"]
    assert row["resting_hr"] == 48
    assert row["steps"] == 12000
    assert row["step_goal"] == 10000
    assert row["stress_high_s"] == 60.0
    assert row["body_battery_max"] is None


def test_hrv_rows():
    response = {"hrvSummaries": [{"calendarDate": "2026-01-01", "lastNightAvg": 60, "baseline": {"balancedLow": 50}}]}
    row = normalize.hrv_rows(response)["2026-01-01"]
    assert row["hrv_avg_ms"] == 60
    assert row["hrv_baseline_low_ms"] == 50


def test_sleep_rows_skip_nights_without_sleep():
    response = [
        {
            "calendarDate": "2026-01-02",
            "sleepTimeSeconds": 28800,
            "sleepStartTimestampLocal": 1767306600000,  # 2026-01-01 22:30 local
            "sleepScores": {"overall": {"value": 80, "qualifierKey": "GOOD"}},
        },
        {"calendarDate": "2026-01-03", "sleepTimeSeconds": None},
    ]
    rows = normalize.sleep_rows(response)
    assert list(rows) == ["2026-01-02"]
    assert rows["2026-01-02"]["sleep_start_local"] == "2026-01-01T22:30"
    assert rows["2026-01-02"]["sleep_score"] == 80


def test_merge_daily():
    merged = normalize.merge_daily({"d1": {"a": 1}}, {"d1": {"b": 2}, "d2": {"b": 3}})
    assert merged == {"d1": {"a": 1, "b": 2}, "d2": {"b": 3}}
