from runlog import db


def test_connect_applies_migrations(tmp_path):
    conn = db.connect(tmp_path / "sub" / "runlog.db")
    tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
    assert {"raw_responses", "activities", "activity_samples", "laps", "daily_health", "sync_state"} <= tables
    assert conn.execute("PRAGMA user_version").fetchone()[0] == db.migrations()[-1][0]


def test_migrate_is_idempotent(tmp_path):
    path = tmp_path / "runlog.db"
    db.connect(path).close()
    conn = db.connect(path)
    assert conn.execute("PRAGMA user_version").fetchone()[0] == db.migrations()[-1][0]


def test_upsert_updates_only_given_columns(tmp_path):
    conn = db.connect(tmp_path / "runlog.db")
    db.upsert(
        conn, "daily_health", {"date": "2026-01-01", "steps": 100, "resting_hr": 50, "updated_at": "t1"}, ["date"]
    )
    db.upsert(conn, "daily_health", {"date": "2026-01-01", "steps": 200, "updated_at": "t2"}, ["date"])
    row = conn.execute("SELECT steps, resting_hr FROM daily_health").fetchone()
    assert tuple(row) == (200, 50)


def test_replace_rows(tmp_path):
    conn = db.connect(tmp_path / "runlog.db")
    db.upsert(
        conn, "activities", {"id": 1, "source": "test", "start_time_local": "2026-01-01", "synced_at": "t"}, ["id"]
    )
    db.replace_rows(conn, "laps", 1, [{"activity_id": 1, "lap_index": 0}, {"activity_id": 1, "lap_index": 1}])
    db.replace_rows(conn, "laps", 1, [{"activity_id": 1, "lap_index": 0}])
    assert conn.execute("SELECT count(*) FROM laps").fetchone()[0] == 1


def test_state(tmp_path):
    conn = db.connect(tmp_path / "runlog.db")
    assert db.get_state(conn, "x") is None
    db.set_state(conn, "x", "a")
    db.set_state(conn, "x", "b")
    assert db.get_state(conn, "x") == "b"
