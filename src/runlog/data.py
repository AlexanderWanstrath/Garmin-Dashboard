"""Read rows from the local database for the metrics. Read-only."""

from __future__ import annotations

import sqlite3

from runlog.metrics import Row


def activities(conn: sqlite3.Connection) -> list[Row]:
    return [dict(r) for r in conn.execute("SELECT * FROM activities ORDER BY start_time_local")]


def samples(conn: sqlite3.Connection, activity_id: int) -> list[Row]:
    query = "SELECT t_offset_s, hr, speed, distance_m FROM activity_samples WHERE activity_id = ? ORDER BY t_offset_s"
    return [dict(r) for r in conn.execute(query, (activity_id,))]


def daily_health(conn: sqlite3.Connection) -> list[Row]:
    return [dict(r) for r in conn.execute("SELECT * FROM daily_health ORDER BY date")]
