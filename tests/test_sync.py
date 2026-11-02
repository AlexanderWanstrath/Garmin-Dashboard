from datetime import date, timedelta

import pytest

from runlog import db, sync
from runlog.sources.fit_files import FitData

TODAY = date(2026, 3, 1)


def activity(activity_id, day, type_key="running"):
    return {
        "activityId": activity_id,
        "startTimeLocal": f"{day.isoformat()} 08:00:00",
        "activityType": {"typeKey": type_key},
        "distance": 5000.0,
    }


class FakeSource:
    name = "fake"

    def __init__(self, activities):
        self.activities = activities
        self.list_calls = []
        self.detail_calls = []
        self.health_calls = []

    def list_activities(self, since):
        self.list_calls.append(since)
        return [a for a in self.activities if since is None or a["startTimeLocal"][:10] >= since.isoformat()]

    def activity_detail(self, activity_id):
        self.detail_calls.append(activity_id)
        return {"summaryDTO": {"minHR": 80.0}}

    def activity_file(self, activity_id):
        return None if activity_id == 2 else b"fit"

    def daily_summaries(self, start, end):
        self.health_calls.append((start, end))
        days = [start + timedelta(days=i) for i in range((end - start).days + 1)]
        return {"data": [{"calendarDate": d.isoformat(), "movement": {"steps": {"value": 1000}}} for d in days]}

    def hrv(self, start, end):
        return {"hrvSummaries": [{"calendarDate": start.isoformat(), "lastNightAvg": 55}]}

    def sleep(self, start, end):
        return []

    def heart_rate_zones(self):
        return [{"sport": "DEFAULT"}]


@pytest.fixture
def conn(tmp_path, monkeypatch):
    fit = FitData(samples=[{"t_offset_s": 0, "hr": 120}], laps=[{"lap_index": 0, "distance_m": 1000.0}], vo2max=50.0)
    monkeypatch.setattr(sync, "parse_fit", lambda content: fit)
    return db.connect(tmp_path / "runlog.db")


def run(conn, source, tmp_path, today=TODAY):
    return sync.run_sync(conn, source, tmp_path, today=today, log=lambda msg: None)


def test_first_sync_loads_everything(conn, tmp_path):
    source = FakeSource([activity(1, date(2026, 2, 1)), activity(2, date(2026, 2, 10), "strength_training")])
    result = run(conn, source, tmp_path)

    assert result.new_activities == 2
    assert source.list_calls == [None]
    row = conn.execute("SELECT min_hr, vo2max, fit_path FROM activities WHERE id = 1").fetchone()
    assert row["min_hr"] == 80.0
    assert row["vo2max"] == 50.0
    assert (tmp_path / "fit" / "1.fit").read_bytes() == b"fit"
    assert conn.execute("SELECT count(*) FROM activity_samples").fetchone()[0] == 1
    assert conn.execute("SELECT count(*) FROM laps").fetchone()[0] == 1
    assert any("activity 2: no FIT file" in w for w in result.warnings)

    # Health data starts at the first activity and runs through today.
    assert result.health_range == (date(2026, 2, 1), TODAY)
    assert result.health_days == (TODAY - date(2026, 2, 1)).days + 1
    assert conn.execute("SELECT hrv_avg_ms FROM daily_health WHERE date = '2026-02-01'").fetchone()[0] == 55
    raw = conn.execute("SELECT count(*) FROM raw_responses WHERE endpoint = 'fake/activity_detail'").fetchone()[0]
    assert raw == 2


def test_second_sync_only_fetches_new(conn, tmp_path):
    source = FakeSource([activity(1, date(2026, 2, 1))])
    run(conn, source, tmp_path)
    source.activities.append(activity(3, date(2026, 3, 2)))
    source.detail_calls.clear()
    source.health_calls.clear()

    result = run(conn, source, tmp_path, today=date(2026, 3, 2))

    assert source.list_calls[-1] == date(2026, 1, 31)  # latest stored activity minus overlap
    assert source.detail_calls == [3]
    assert result.new_activities == 1
    assert result.known_activities == 1
    # Health data is refetched from a few days before the last sync.
    assert source.health_calls == [(TODAY - timedelta(days=sync.HEALTH_REFETCH_DAYS), date(2026, 3, 2))]


def test_health_is_chunked(conn, tmp_path):
    source = FakeSource([])
    sync.run_sync(conn, source, tmp_path, today=TODAY, start_date=TODAY - timedelta(days=59), log=lambda m: None)
    assert len(source.health_calls) == 3
    assert all((end - start).days < sync.HEALTH_CHUNK_DAYS for start, end in source.health_calls)
    assert source.health_calls[-1][1] == TODAY
