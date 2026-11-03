import textwrap
from datetime import date, timedelta

import pytest

from runlog import db

TODAY = date.today()
RUN_DAY = TODAY - timedelta(days=1)


@pytest.fixture
def project(tmp_path):
    """A project folder with config, plan and a database of synthetic data."""
    (tmp_path / "config.yaml").write_text(
        textwrap.dedent(
            f"""
            paths: {{data_dir: data, plan_file: plan.yaml}}
            events:
              - {{name: Test race, date: {TODAY + timedelta(days=10)}, goal: "40:00"}}
            """
        ),
        encoding="utf-8",
    )
    (tmp_path / "plan.yaml").write_text(
        f"sessions:\n  - {{date: {RUN_DAY}, type: E, name: Easy, km: 8, pace: ['6:50', '7:15'], hr_max: 140}}\n",
        encoding="utf-8",
    )
    conn = db.connect(tmp_path / "data" / "runlog.db")
    db.upsert(
        conn,
        "activities",
        {
            "id": 1,
            "source": "test",
            "start_time_local": f"{RUN_DAY} 08:00:00",
            "type": "running",
            "distance_m": 8000.0,
            "duration_s": 3360.0,
            "avg_moving_speed": 1000 / 420,
            "avg_hr": 135.0,
            "garmin_rpe": 30,
            "synced_at": "t",
        },
        ["id"],
    )
    db.replace_rows(
        conn, "activity_samples", 1, [{"activity_id": 1, "t_offset_s": i, "hr": 135, "speed": 2.4} for i in range(1800)]
    )
    db.replace_rows(conn, "laps", 1, [{"activity_id": 1, "lap_index": 0, "distance_m": 1000.0, "avg_speed": 2.4}])
    for i in range(10):
        day = (TODAY - timedelta(days=i)).isoformat()
        db.upsert(
            conn,
            "daily_health",
            {"date": day, "hrv_avg_ms": 95, "resting_hr": 40, "sleep_s": 28000, "deep_s": 5000, "updated_at": "t"},
            ["date"],
        )
    conn.execute(
        "INSERT INTO manual_entries (date, tendon_pain, legs, created_at) VALUES (?, 1, 'fresh', 't')",
        (TODAY.isoformat(),),
    )
    conn.commit()
    conn.close()
    return tmp_path
