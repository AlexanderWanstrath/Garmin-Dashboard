from datetime import date, timedelta

from runlog.metrics.volume import Week
from runlog.warnings import morning_check, volume_warnings

DAY = date(2030, 1, 10)


def daily(values):
    """values: list of (hrv, resting_hr), the last one is DAY."""
    start = DAY - timedelta(days=len(values) - 1)
    return [
        {"date": (start + timedelta(days=i)).isoformat(), "hrv_avg_ms": hrv, "resting_hr": rhr}
        for i, (hrv, rhr) in enumerate(values)
    ]


def entry(**fields):
    return {"date": DAY.isoformat(), "created_at": "t", "id": 1, **fields}


def signals(check):
    return {s.name: s.level for s in check.signals}


def test_all_green():
    check = morning_check(DAY, daily([(95, 40)]), [entry(tendon_pain=1, legs="fresh")])
    assert signals(check) == {"tendon": "green", "hrv": "green", "resting_hr": "green", "legs": "green"}
    assert check.level == "green"
    assert check.advice == "Train as planned."


def test_worst_signal_decides():
    check = morning_check(DAY, daily([(95, 40)]), [entry(tendon_pain=2, legs="fresh")])
    assert check.level == "yellow"
    assert check.advice.startswith("Long run 20-30 % shorter")


def test_tendon_levels():
    assert signals(morning_check(DAY, [], [entry(tendon_pain=3)]))["tendon"] == "yellow"
    assert signals(morning_check(DAY, [], [entry(tendon_pain=4)]))["tendon"] == "red"
    assert signals(morning_check(DAY, [], [entry(tendon_pain=0, startup_pain=1)]))["tendon"] == "red"


def test_latest_entry_of_the_day_counts():
    manual = [entry(tendon_pain=4, created_at="08:00"), entry(tendon_pain=1, created_at="09:00", id=2)]
    assert signals(morning_check(DAY, [], manual))["tendon"] == "green"


def test_hrv_one_night_yellow_two_nights_red():
    assert signals(morning_check(DAY, daily([(95, 40), (80, 40)]), []))["hrv"] == "yellow"
    assert signals(morning_check(DAY, daily([(82, 40), (80, 40)]), []))["hrv"] == "red"


def test_resting_hr_levels():
    assert signals(morning_check(DAY, daily([(95, 43)]), []))["resting_hr"] == "yellow"
    assert signals(morning_check(DAY, daily([(95, 40), (95, 46)]), []))["resting_hr"] == "yellow"
    assert signals(morning_check(DAY, daily([(95, 47), (95, 46)]), []))["resting_hr"] == "red"


def test_missing_data_is_not_a_signal():
    check = morning_check(DAY, [], [])
    assert check.level is None
    assert all(s.level is None for s in check.signals)


def test_config_overrides_thresholds():
    cfg = {"morning_check": {"hrv_ms": {"low": 60, "red_days": 2}}}
    assert signals(morning_check(DAY, daily([(70, 40)]), [], cfg))["hrv"] == "green"


def week(start, km, inc):
    return Week(start, km, 3, 0, 0, 0, None, inc)


def test_volume_warning_against_3_week_mean():
    weeks = [week(DAY, 40, 5.0), week(DAY + timedelta(days=7), 50, 25.0)]
    (warning,) = volume_warnings(weeks, 10)
    assert "+25 %" in warning.reason
    assert volume_warnings([week(DAY, 40, 8.0)], 10) == []
