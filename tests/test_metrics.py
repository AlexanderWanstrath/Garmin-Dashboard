from datetime import date, timedelta

import pytest

from runlog.metrics.decoupling import MIN_MOVING_S, decoupling_pct
from runlog.metrics.efficiency import efficiency_factor, is_easy_run
from runlog.metrics.intensity import weekly_intensity
from runlog.metrics.recovery import recovery
from runlog.metrics.volume import weekly_volume

MONDAY = date(2026, 1, 5)


def run(day, km, type_="running", zones=(0, 0, 0, 0, 0), **extra):
    row = {"type": type_, "start_time_local": f"{day.isoformat()} 08:00:00", "distance_m": km * 1000, "duration_s": 0}
    row.update({f"hr_zone_{i}_s": z for i, z in enumerate(zones, 1)})
    row.update(extra)
    return row


# --- volume -----------------------------------------------------------------


def test_weekly_volume_sums_runs_only_and_fills_gaps():
    acts = [
        run(MONDAY, 10),
        run(MONDAY + timedelta(days=2), 5),
        run(MONDAY + timedelta(days=3), 99, type_="strength_training"),
        run(MONDAY + timedelta(days=14), 12, type_="track_running"),
    ]
    weeks = weekly_volume(acts, long_run_min_km=10)
    assert [w.start for w in weeks] == [MONDAY, MONDAY + timedelta(days=7), MONDAY + timedelta(days=14)]
    assert [w.km for w in weeks] == [15, 0, 12]
    assert weeks[0].runs == 2
    assert weeks[0].longest_km == 10
    assert weeks[0].long_runs == 1
    assert weeks[1].increase_vs_prev_pct == -100.0
    assert weeks[2].increase_vs_prev_pct is None  # previous week had 0 km


def test_increase_rates():
    acts = [run(MONDAY + timedelta(days=7 * i), km) for i, km in enumerate([20, 20, 20, 22, 30])]
    weeks = weekly_volume(acts, long_run_min_km=14)
    assert weeks[3].increase_vs_prev_pct == 10.0
    assert weeks[3].increase_vs_3wk_pct == 10.0
    assert weeks[4].increase_vs_prev_pct == pytest.approx(36.4)
    assert weeks[4].increase_vs_3wk_pct == pytest.approx(45.2)
    assert weeks[2].increase_vs_3wk_pct is None  # fewer than three previous weeks


def test_weekly_volume_until_adds_trailing_empty_weeks():
    weeks = weekly_volume([run(MONDAY, 5)], long_run_min_km=10, until=MONDAY + timedelta(days=10))
    assert [w.km for w in weeks] == [5, 0]


def test_weekly_volume_empty():
    assert weekly_volume([], long_run_min_km=10) == []


# --- decoupling ---------------------------------------------------------------


def samples(n, speed, hr_first, hr_second, start=0):
    return [{"t_offset_s": start + i, "speed": speed, "hr": hr_first if i < n // 2 else hr_second} for i in range(n)]


def test_decoupling_zero_when_steady():
    assert decoupling_pct(samples(MIN_MOVING_S, 3.0, 150, 150)) == 0.0


def test_decoupling_positive_when_hr_drifts():
    # EF1 = 3/150, EF2 = 3/165 -> (1 - 150/165) = 9.1 %
    assert decoupling_pct(samples(MIN_MOVING_S * 2, 3.0, 150, 165)) == pytest.approx(9.1)


def test_decoupling_ignores_pauses_and_warmup():
    data = samples(MIN_MOVING_S, 3.0, 150, 150, start=600)
    warmup = [{"t_offset_s": i, "speed": 2.0, "hr": 100} for i in range(600)]
    pause = [{"t_offset_s": 10_000 + i, "speed": 0.0, "hr": 190} for i in range(300)]
    assert decoupling_pct(warmup + data + pause, warmup_s=600) == 0.0


def test_decoupling_none_for_short_runs():
    assert decoupling_pct(samples(MIN_MOVING_S - 1, 3.0, 150, 150)) is None


# --- efficiency ----------------------------------------------------------------


def test_efficiency_factor():
    assert efficiency_factor({"avg_moving_speed": 3.0, "avg_hr": 150}) == 1.2
    assert efficiency_factor({"avg_speed": 3.0, "avg_hr": None}) is None
    # Broken recording: 1.4 km logged with 3 minutes of moving time.
    assert efficiency_factor({"avg_moving_speed": 7.74, "avg_hr": 154}) is None


def test_easy_run_classification():
    assert is_easy_run(run(MONDAY, 10, zones=(600, 2400, 300, 0, 0)), easy_zones=[1, 2])
    assert not is_easy_run(run(MONDAY, 10, zones=(0, 1200, 1200, 600, 0)), easy_zones=[1, 2])
    assert not is_easy_run(run(MONDAY, 10, type_="strength_training", zones=(3000, 0, 0, 0, 0)), easy_zones=[1, 2])
    assert not is_easy_run(run(MONDAY, 10), easy_zones=[1, 2])  # no zone data


# --- intensity -----------------------------------------------------------------


def test_weekly_intensity():
    acts = [
        run(MONDAY, 10, zones=(600, 2400, 0, 0, 0)),
        run(MONDAY + timedelta(days=1), 8, zones=(0, 600, 300, 300, 0)),
        run(MONDAY + timedelta(days=2), 0, type_="strength_training", zones=(0, 0, 0, 0, 9999)),
    ]
    (week,) = weekly_intensity(acts, easy_zones=[1, 2])
    assert week.easy_s == 3600
    assert week.hard_s == 600
    assert week.easy_pct == pytest.approx(85.7)


# --- recovery ------------------------------------------------------------------


def day_rows(values, **extra):
    return [
        {"date": (MONDAY + timedelta(days=i)).isoformat(), "hrv_avg_ms": hrv, "resting_hr": rhr, **extra}
        for i, (hrv, rhr) in enumerate(values)
    ]


def test_recovery_uses_garmin_baseline_and_7_day_mean():
    rows = day_rows([(60, 50)] * 6 + [(39, 50)], hrv_baseline_low_ms=50, hrv_baseline_high_ms=70)
    last = recovery(rows)[-1]
    assert last.hrv_7d_ms == 57.0
    assert last.hrv_vs_baseline == "within"
    rows = day_rows([(40, 50)] * 7, hrv_baseline_low_ms=50, hrv_baseline_high_ms=70)
    assert recovery(rows)[-1].hrv_vs_baseline == "below"


def test_recovery_falls_back_to_config_range():
    rows = day_rows([(90, 50)])
    (day,) = recovery(rows, hrv_range=(50, 80))
    assert (day.hrv_low_ms, day.hrv_high_ms, day.hrv_vs_baseline) == (50, 80, "above")


def test_resting_hr_rolling_baseline_needs_enough_history():
    rows = day_rows([(60, 48)] * 20 + [(60, 55)])
    result = recovery(rows)
    assert result[10].resting_hr_baseline is None  # only 10 days of history
    assert result[-1].resting_hr_baseline == 48
    assert result[-1].resting_hr_delta == 7


def test_resting_hr_config_baseline():
    (day,) = recovery(day_rows([(60, 52)]), resting_hr_baseline=50)
    assert day.resting_hr_delta == 2
