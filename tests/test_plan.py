from datetime import date, timedelta
from pathlib import Path

import pytest

from runlog.plan import (
    Plan,
    PlanError,
    PlanWeek,
    Session,
    check_fuel,
    check_reps,
    evaluate,
    format_pace,
    load_plan,
    match_sessions,
    parse_pace,
    weekly_status,
)

EXAMPLE = Path(__file__).resolve().parents[1] / "plan.example.yaml"
TUE = date(2030, 1, 8)


def run(activity_id, day, km, **extra):
    return {
        "id": activity_id,
        "type": "running",
        "start_time_local": f"{day.isoformat()} 08:00:00",
        "distance_m": km * 1000,
        **extra,
    }


def lap(pace, intensity="active"):
    return {
        "intensity": intensity,
        "avg_speed": 1000 / parse_pace(pace),
        "distance_m": 1000,
        "timer_s": parse_pace(pace),
    }


def test_pace_roundtrip():
    assert parse_pace("4:05") == 245
    assert format_pace(245.4) == "4:05"


def test_example_plan_loads():
    plan = load_plan(EXAMPLE)
    q = plan.sessions[0]
    assert (q.type, q.reps, q.rep_pace_s) == ("Q", 5, (260, 265))
    assert plan.sessions[1].pace_s == (360, 390)
    assert plan.weeks[0].km == (40, 45)
    assert plan.weeks[1].km == (46, 46)


def test_unknown_type_is_rejected(tmp_path):
    path = tmp_path / "plan.yaml"
    path.write_text("sessions:\n  - {date: 2030-01-01, type: X}\n", encoding="utf-8")
    with pytest.raises(PlanError, match="unknown session type"):
        load_plan(path)


def test_missing_plan(tmp_path):
    with pytest.raises(PlanError, match="plan.example.yaml"):
        load_plan(tmp_path / "plan.yaml")


def test_matching_prefers_same_day_then_nearby():
    plan = Plan([], [Session(TUE, "Q", "Q"), Session(TUE + timedelta(days=1), "E", "E")])
    acts = [run(1, TUE + timedelta(days=1), 8), run(2, TUE + timedelta(days=2), 10)]
    matches = match_sessions(plan, acts, today=TUE + timedelta(days=5))
    assert matches[1]["id"] == 1  # same day
    assert matches[0]["id"] == 2  # moved by two days


def test_no_match_before_plan_start_or_from_the_past_for_today():
    plan = Plan([], [Session(TUE, "R", "Test")])
    before_plan = run(1, TUE - timedelta(days=2), 10)  # Sunday, previous week
    (result,) = evaluate(plan, [before_plan], today=TUE)
    assert result.status == "upcoming"
    plan = Plan([], [Session(TUE - timedelta(days=1), "E", "E"), Session(TUE, "R", "Test")])
    yesterday = run(2, TUE - timedelta(days=1), 8)
    results = evaluate(plan, [yesterday], today=TUE)
    assert [r.status for r in results] == ["done", "upcoming"]


def test_runs_of_the_same_day_add_up():
    """Warm-up, test and cool-down recorded as three activities count for one session."""
    plan = Plan([], [Session(TUE, "R", "5 km test", km=(9, 10))])
    acts = [run(1, TUE, 2), run(2, TUE, 5, avg_moving_speed=1000 / 232), run(3, TUE, 2.5)]
    (result,) = evaluate(plan, acts, today=TUE + timedelta(days=1))
    assert result.activity_id == 2
    assert sorted(result.activity_ids) == [1, 2, 3]
    assert result.actual_km == 9.5
    assert result.findings == []
    assert format_pace(result.pace_s) == "3:52"


def test_status_missed_and_upcoming():
    plan = Plan([], [Session(TUE, "E", "E"), Session(TUE + timedelta(days=3), "E", "E")])
    results = evaluate(plan, [], today=TUE + timedelta(days=3))
    assert [r.status for r in results] == ["missed", "upcoming"]


def test_easy_run_too_fast_and_hr_over_cap():
    session = Session(TUE, "E", "Easy", km=(8, 8), pace_s=(410, 435), hr_max=140)
    activity = run(1, TUE, 8, avg_moving_speed=1000 / 390)  # 6:30/km
    samples = [{"hr": 150 if i < 20 else 130, "speed": 2.5} for i in range(100)]
    (result,) = evaluate(Plan([], [session]), [activity], TUE, samples_for=lambda i: samples)
    assert result.status == "done"
    assert any("too fast: 6:30/km" in f for f in result.findings)
    assert any("20% of moving time above 140" in f for f in result.findings)


def test_easy_run_as_planned():
    session = Session(TUE, "E", "Easy", km=(8, 8), pace_s=(410, 435), hr_max=140)
    activity = run(1, TUE, 8.2, avg_moving_speed=1000 / 420)
    samples = [{"hr": 130, "speed": 2.4}] * 100
    (result,) = evaluate(Plan([], [session]), [activity], TUE, samples_for=lambda i: samples)
    assert result.findings == []


def test_distance_check():
    session = Session(TUE, "L", "Long", km=(23, 23))
    (result,) = evaluate(Plan([], [session]), [run(1, TUE, 18)], TUE)
    assert result.findings == ["shorter than planned: 18.0 km instead of 23 km"]


def test_reps_follow_the_rules():
    session = Session(TUE, "Q", "4 x 1000", reps=4, rep_pace_s=(parse_pace("3:58"), parse_pace("4:02")))
    laps = [lap("6:30", "warmup"), lap("4:00"), lap("3:59"), lap("4:01"), lap("4:00"), lap("6:40", "cooldown")]
    assert check_reps(session, laps, tolerance_s=2) == []


def test_reps_too_fast_first_and_last_fastest():
    session = Session(TUE, "Q", "5 x 1000", reps=5, rep_pace_s=(parse_pace("3:55"), parse_pace("3:55")))
    laps = [lap(p) for p in ["3:49", "3:47", "3:42", "3:41", "3:32"]]  # pattern from 28.10.
    findings = check_reps(session, laps, tolerance_s=2)
    assert any(f.startswith("faster than 3:55/km: #1 3:49") for f in findings)
    assert "first rep faster than the plan's fastest pace" in findings
    assert "last rep was the fastest" in findings


def test_reps_count_and_missing_workout():
    session = Session(TUE, "Q", "4 x 1000", reps=4)
    assert check_reps(session, [lap("4:00")] * 3, 2) == ["3 work intervals instead of 4"]
    assert check_reps(session, [lap("5:00", "warmup")], 2)[0].startswith("no work intervals")


def test_fuel():
    session = Session(TUE, "L", "Long", fuel_g_per_h=40)
    activity = {"duration_s": 2 * 3600}
    assert check_fuel(session, activity, None) == ["no fueling logged (target 40 g/h)"]
    assert check_fuel(session, activity, 20) == ["fueling 10 g/h, target 40 g/h"]
    assert check_fuel(session, activity, 80) == []


def test_weekly_status():
    monday = date(2030, 1, 7)
    plan = Plan([PlanWeek(monday, (40, 45)), PlanWeek(monday + timedelta(days=7), (46, 46))], [])
    acts = [run(1, monday, 20), run(2, monday + timedelta(days=2), 22), run(3, monday + timedelta(days=8), 10)]
    results = weekly_status(plan, acts, today=monday + timedelta(days=9))
    assert [(r.actual_km, r.status) for r in results] == [(42, "within"), (10, "in progress")]
