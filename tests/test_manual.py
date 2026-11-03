from datetime import date

import pytest

from runlog import data, db
from runlog.manual import EntryError, add_entry
from runlog.metrics.intensity import hr_split, weekly_intensity_by_hr

DAY = date(2030, 1, 10)


@pytest.fixture
def conn(tmp_path):
    conn = db.connect(tmp_path / "runlog.db")
    for activity_id, day, type_ in [(1, "2030-01-08", "running"), (2, "2030-01-09", "strength_training")]:
        db.upsert(
            conn,
            "activities",
            {"id": activity_id, "source": "t", "start_time_local": f"{day} 08:00:00", "type": type_, "synced_at": "t"},
            ["id"],
        )
    return conn


def test_morning_entry(conn):
    add_entry(conn, DAY, tendon=2, legs="schwer", hip_pain=True)
    (row,) = data.manual_entries(conn)
    assert (row["date"], row["tendon_pain"], row["legs"], row["hip_pain"], row["startup_pain"]) == (
        "2030-01-10",
        2,
        "heavy",
        1,
        0,
    )


def test_fuel_goes_to_last_run_and_its_date(conn):
    add_entry(conn, DAY, fuel_g=45)
    (row,) = data.manual_entries(conn)
    assert (row["activity_id"], row["date"], row["fuel_g"]) == (1, "2030-01-08", 45)
    assert data.fuel_g(conn, 1) == 45
    assert data.fuel_g(conn, 2) is None


@pytest.mark.parametrize(
    ("kwargs", "message"),
    [
        ({"tendon": 11}, "between 0 and 10"),
        ({"legs": "tired"}, "--legs must be one of"),
        ({}, "nothing to log"),
        ({"fuel_g": 10, "activity": "999"}, "no activity found"),
        ({"fuel_g": 10, "activity": "abc"}, "'last' or an activity id"),
    ],
)
def test_invalid_entries(conn, kwargs, message):
    with pytest.raises(EntryError, match=message):
        add_entry(conn, DAY, **kwargs)


def test_hr_split_and_weekly_intensity_by_hr():
    samples = [{"hr": 130, "speed": 2.5}] * 80 + [{"hr": 150, "speed": 2.5}] * 20 + [{"hr": 170, "speed": 0}] * 50
    assert hr_split(samples, 140) == (80, 20)
    acts = [{"id": 1, "type": "running", "start_time_local": "2030-01-08 08:00:00"}]
    (week,) = weekly_intensity_by_hr(acts, lambda i: samples, 140)
    assert week.easy_pct == 80.0
