"""Synthetic training data for the public demo and for tests. Nothing here comes from real data.

A made-up runner trains for twelve weeks toward a marathon: quality on Tuesday, a long run on
Thursday that grows each week (every fourth week is a recovery week), easy runs otherwise.
Runs are simulated second by second, so decoupling, laps and time in zones come out of the
same code as for real Garmin data. A few deviations from the plan are built in on purpose.
"""

from __future__ import annotations

import random
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

import yaml

from runlog import db
from runlog.metrics import week_start

WEEKS = 12
SEED = 7
ZONE_FLOORS = [100, 118, 137, 155, 172]  # made-up athlete, max HR 190
EASY_HR, LONG_HR = 145, 150
EASY_PACE, LONG_PACE = ("6:00", "6:30"), ("5:55", "6:25")


@dataclass
class Segment:
    meters: float | None
    seconds: float | None
    speed: float  # m/s
    hr: float
    intensity: str = "active"


def _pace(text: str) -> float:
    minutes, seconds = text.split(":")
    return 1000 / (int(minutes) * 60 + int(seconds))


def easy(km: float, pace: str = "6:15", hr: float = 136, fitness: float = 0) -> list[Segment]:
    """`fitness` (0 to ~0.05) makes the same heart rate a little faster over the weeks."""
    return [Segment(km * 1000, None, _pace(pace) * (1 + fitness), hr)]


def long_run(km: float, fitness: float = 0) -> list[Segment]:
    return [Segment(km * 1000, None, _pace("6:10") * (1 + fitness), 137)]


def intervals(reps: list[str]) -> list[Segment]:
    segments = [Segment(2000, None, _pace("6:20"), 132, "warmup")]
    for i, pace in enumerate(reps):
        segments.append(Segment(1000, None, _pace(pace), 170, "active"))
        if i < len(reps) - 1:
            segments.append(Segment(None, 90, _pace("8:00"), 145, "recovery"))
    segments.append(Segment(2000, None, _pace("6:40"), 135, "cooldown"))
    return segments


def simulate(segments: list[Segment], rng: random.Random, drift_bpm: float = 0) -> list[dict[str, Any]]:
    """Per-second samples: heart rate follows the target with a lag, plus noise and slow drift."""
    samples: list[dict[str, Any]] = []
    total = sum(s.meters / s.speed if s.meters else s.seconds for s in segments)
    hr, distance, t = 100.0, 0.0, 0
    for seg in segments:
        seg_start = distance
        seg_t = 0
        while (seg.meters and distance - seg_start < seg.meters) or (seg.seconds and seg_t < seg.seconds):
            speed = max(0.8, seg.speed * (1 + rng.gauss(0, 0.03)))
            target = seg.hr + drift_bpm * t / total
            hr += (target - hr) / 25 + rng.gauss(0, 0.8)
            distance += speed
            samples.append(
                {
                    "t_offset_s": t,
                    "hr": round(hr),
                    "speed": round(speed, 3),
                    "distance_m": round(distance, 1),
                    "intensity": seg.intensity,
                }
            )
            t += 1
            seg_t += 1
    return samples


def laps_from(samples: list[dict[str, Any]], structured: bool) -> list[dict[str, Any]]:
    """Workout steps become laps for structured sessions, otherwise one lap per km (auto lap)."""
    groups: list[list[dict[str, Any]]] = []
    for s in samples:
        new = not groups or (
            s["intensity"] != groups[-1][-1]["intensity"]
            if structured
            else int(s["distance_m"] // 1000) != int(groups[-1][0]["distance_m"] // 1000)
        )
        if new:
            groups.append([])
        groups[-1].append(s)
    laps = []
    for i, g in enumerate(groups):
        meters = g[-1]["distance_m"] - (groups[i - 1][-1]["distance_m"] if i else 0)
        laps.append(
            {
                "lap_index": i,
                "distance_m": round(meters, 1),
                "timer_s": len(g),
                "elapsed_s": len(g),
                "avg_hr": round(sum(s["hr"] for s in g) / len(g)),
                "max_hr": max(s["hr"] for s in g),
                "avg_speed": round(meters / len(g), 3),
                "intensity": g[0]["intensity"] if structured else "active",
                "lap_trigger": "session_end" if i == len(groups) - 1 else ("time" if structured else "distance"),
            }
        )
    return laps


def activity_row(
    activity_id: int, start: datetime, name: str, samples: list[dict[str, Any]], vo2max: float, rpe: int
) -> dict[str, Any]:
    moving = len(samples)
    distance = samples[-1]["distance_m"]
    hrs = [s["hr"] for s in samples]
    zones = [0] * 5
    for h in hrs:
        zones[max(i for i, floor in enumerate(ZONE_FLOORS) if h >= floor) if h >= ZONE_FLOORS[0] else 0] += 1
    hard = sum(zones[3:]) / moving
    row = {
        "id": activity_id,
        "source": "demo",
        "start_time_local": start.strftime("%Y-%m-%d %H:%M:%S"),
        "start_time_gmt": start.strftime("%Y-%m-%d %H:%M:%S"),
        "type": "running",
        "name": name,
        "distance_m": distance,
        "duration_s": float(moving),
        "elapsed_s": float(moving + 30),
        "moving_s": float(moving),
        "avg_hr": round(sum(hrs) / moving, 1),
        "max_hr": float(max(hrs)),
        "min_hr": float(min(hrs)),
        "avg_speed": distance / (moving + 30),
        "avg_moving_speed": distance / moving,
        "max_speed": max(s["speed"] for s in samples),
        "elevation_gain_m": round(distance / 1000 * 4),
        "avg_cadence_spm": 168.0,
        "aerobic_te": round(min(5.0, 2.2 + distance / 12000 + hard * 3), 1),
        "anaerobic_te": round(min(4.0, hard * 6), 1),
        "garmin_rpe": rpe,
        "calories_kcal": round(distance / 1000 * 62),
        "steps": round(moving * 2.8),
        "lap_count": None,
        "vo2max": vo2max,
        "synced_at": start.isoformat(),
    }
    for i in range(5):
        row[f"hr_zone_{i + 1}_s"] = float(zones[i])
    return row


def schedule(week: int) -> dict[int, tuple[str, str, float]]:
    """weekday -> (plan type, name, km) for training week `week` (0-based)."""
    recovery = week % 4 == 3
    long_km = round((16 + week * 1.0) * (0.7 if recovery else 1), 1)
    plan = {
        1: ("Q", "5 x 1000 m", 9.0),
        2: ("E", "Easy run", 8.0),
        3: ("L", f"Long run {long_km:g} km", long_km),
        5: ("E", "Easy run", 6.0),
        6: ("E", "Easy run", 10.0 if not recovery else 7.0),
    }
    if recovery:
        plan[1] = ("E", "Easy run + strides", 7.0)
    return plan


def generate(target: Path, today: date | None = None, seed: int = SEED) -> Path:
    """Write data/runlog.db, plan.yaml and config.yaml for the demo athlete into `target`."""
    today = today or date.today()
    rng = random.Random(seed)
    target.mkdir(parents=True, exist_ok=True)
    db_path = target / "data" / "runlog.db"
    if db_path.exists():
        db_path.unlink()
    conn = db.connect(db_path)

    first_monday = week_start(today) - timedelta(weeks=WEEKS - 1)
    sessions, weeks, hard_days = [], [], set()
    activity_id = 1_000_000
    for w in range(WEEKS + 1):
        monday = first_monday + timedelta(weeks=w)
        plan = schedule(w)
        weeks.append({"start": monday, "km": round(sum(km for _, _, km in plan.values()) * 1.1)})
        for weekday, (kind, name, km) in plan.items():
            day = monday + timedelta(days=weekday)
            session = {"date": day, "type": kind, "name": name, "km": km}
            if kind == "Q":
                session["reps"] = {"count": 5, "pace": ["3:55", "4:00"]}
            elif kind == "L":
                session.update(pace=list(LONG_PACE), hr_max=LONG_HR, fuel_g_per_h=45)
            else:
                session.update(pace=list(EASY_PACE), hr_max=EASY_HR)
            sessions.append(session)
            if day >= today:
                continue
            last_week = w == WEEKS - 2
            fitness = w * 0.004
            if kind == "Q":
                reps = ["3:56", "3:55", "3:54", "3:53", "3:52"]
                if last_week:  # built-in deviation: reps get faster and faster
                    reps = ["3:50", "3:47", "3:44", "3:41", "3:36"]
                segments, rpe = intervals(reps), 70
            elif kind == "L":
                segments, rpe = long_run(km, fitness), 50
            elif last_week and weekday == 2:  # built-in deviation: easy run too fast
                segments, rpe = easy(km, "5:45", 152), 50
            else:
                segments, rpe = easy(km * rng.uniform(0.95, 1.05), fitness=fitness), 30
            # Long runs drift less as the aerobic base grows.
            drift = 11 - w * 0.45 if kind == "L" else 2
            samples = simulate(segments, rng, drift_bpm=drift)
            vo2 = round(50.5 + w * 0.12 + rng.gauss(0, 0.15), 1)
            start = datetime.combine(day, datetime.min.time()) + timedelta(hours=7, minutes=rng.randint(0, 50))
            activity_id += 1
            row = activity_row(activity_id, start, name, samples, vo2, rpe)
            laps = laps_from(samples, structured=kind == "Q")
            row["lap_count"] = len(laps)
            db.upsert(conn, "activities", row, ["id"])
            db.replace_rows(
                conn,
                "activity_samples",
                activity_id,
                [{"activity_id": activity_id, **{k: v for k, v in s.items() if k != "intensity"}} for s in samples],
            )
            db.replace_rows(conn, "laps", activity_id, [{"activity_id": activity_id, **lap} for lap in laps])
            if kind in ("Q", "L"):
                hard_days.add(day)
            if kind == "L" and not last_week:
                hours = len(samples) / 3600
                conn.execute(
                    "INSERT INTO manual_entries (date, activity_id, fuel_g, created_at) VALUES (?, ?, ?, ?)",
                    (day.isoformat(), activity_id, round(hours * rng.uniform(38, 50)), start.isoformat()),
                )

    day = first_monday
    while day <= today:
        after_hard = (day - timedelta(days=1)) in hard_days
        hrv = round(66 + rng.gauss(0, 4) - (7 if after_hard else 0))
        sleep = round(rng.gauss(7.4, 0.5) * 3600)
        row = {
            "date": day.isoformat(),
            "resting_hr": round(47 + rng.gauss(0, 1.2) + (2 if after_hard else 0)),
            "steps": round(rng.uniform(7000, 14000)),
            "calories_total_kcal": round(rng.uniform(2300, 3200)),
            "stress_avg": round(rng.uniform(22, 38)),
            "body_battery_max": round(rng.uniform(70, 96)),
            "body_battery_min": round(rng.uniform(15, 35)),
            "hrv_avg_ms": hrv,
            "hrv_baseline_low_ms": 58 if day >= first_monday + timedelta(days=21) else None,
            "hrv_baseline_high_ms": 76 if day >= first_monday + timedelta(days=21) else None,
            "sleep_s": sleep,
            "deep_s": round(sleep * rng.uniform(0.15, 0.22)),
            "rem_s": round(sleep * rng.uniform(0.18, 0.25)),
            "awake_s": round(sleep * rng.uniform(0.02, 0.06)),
            "sleep_score": round(rng.uniform(68, 92)),
            "updated_at": day.isoformat(),
        }
        row["light_s"] = sleep - row["deep_s"] - row["rem_s"] - row["awake_s"]
        db.upsert(conn, "daily_health", row, ["date"])
        if day > today - timedelta(days=14):
            conn.execute(
                "INSERT INTO manual_entries (date, tendon_pain, legs, startup_pain, hip_pain, created_at)"
                " VALUES (?, ?, ?, 0, 0, ?)",
                (day.isoformat(), rng.choice([0, 0, 1, 1, 2]), "heavy" if after_hard else "fresh", day.isoformat()),
            )
        day += timedelta(days=1)
    conn.commit()
    conn.close()

    plan_start = week_start(today) - timedelta(weeks=3)
    (target / "plan.yaml").write_text(
        "# Demo training plan (synthetic)\n"
        + yaml.safe_dump(
            {
                "weeks": [w for w in weeks if w["start"] >= plan_start],
                "sessions": [s for s in sessions if s["date"] >= plan_start],
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    (target / "config.yaml").write_text(
        "# Demo config (synthetic athlete)\n"
        + yaml.safe_dump(
            {
                "paths": {"data_dir": "data", "plan_file": "plan.yaml"},
                "events": [
                    {"name": "10 km race", "date": today + timedelta(days=24), "goal": "41:30"},
                    {"name": "Marathon", "date": today + timedelta(days=150), "goal": "3:20:00"},
                ],
                "intensity": {"easy_hr_max": EASY_HR, "long_hr_max": LONG_HR, "easy_share_min": 0.8},
                "morning_check": {
                    "tendon": {"yellow": 2, "red": 4},
                    "hrv_ms": {"low": 58, "red_days": 2},
                    "resting_hr_bpm": {"yellow": 50, "red": 53, "red_days": 2},
                },
                "metrics": {"long_run_min_km": 14, "decoupling_warmup_min": 10, "easy_zones": [1, 2]},
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    return target
