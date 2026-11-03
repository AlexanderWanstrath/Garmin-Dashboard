"""Manual entries: morning check (tendon, legs, hip) and fueling per activity."""

from __future__ import annotations

import sqlite3
from datetime import date, datetime

LEGS_ALIASES = {
    "fresh": "fresh",
    "locker": "fresh",
    "heavy": "heavy",
    "schwer": "heavy",
    "etwas-schwer": "heavy",
    "very-heavy": "very_heavy",
    "very_heavy": "very_heavy",
    "sehr-schwer": "very_heavy",
}


class EntryError(Exception):
    """The entry is invalid or refers to an unknown activity."""


def resolve_activity(conn: sqlite3.Connection, ref: str, day: date | None = None) -> sqlite3.Row:
    """'last' = latest run (on or before `day` if given), otherwise an activity id."""
    if ref == "last":
        query = "SELECT id, start_time_local FROM activities WHERE type LIKE '%running%'"
        params: tuple = ()
        if day:
            query += " AND substr(start_time_local, 1, 10) <= ?"
            params = (day.isoformat(),)
        row = conn.execute(query + " ORDER BY start_time_local DESC LIMIT 1", params).fetchone()
    else:
        try:
            activity_id = int(ref)
        except ValueError as exc:
            raise EntryError(f"--activity must be 'last' or an activity id, got {ref!r}") from exc
        row = conn.execute("SELECT id, start_time_local FROM activities WHERE id = ?", (activity_id,)).fetchone()
    if row is None:
        raise EntryError(f"no activity found for {ref!r} (run 'runlog sync' first?)")
    return row


def add_entry(
    conn: sqlite3.Connection,
    day: date,
    *,
    tendon: int | None = None,
    startup_pain: bool = False,
    legs: str | None = None,
    hip_pain: bool = False,
    fuel_g: float | None = None,
    activity: str | None = None,
    note: str | None = None,
) -> int:
    if tendon is not None and not 0 <= tendon <= 10:
        raise EntryError("--tendon must be between 0 and 10")
    if legs is not None and legs not in LEGS_ALIASES:
        raise EntryError(f"--legs must be one of {', '.join(LEGS_ALIASES)}")
    if fuel_g is not None and fuel_g < 0:
        raise EntryError("--fuel must not be negative")
    if fuel_g is not None and activity is None:
        activity = "last"
    morning = tendon is not None or legs is not None or startup_pain or hip_pain
    if fuel_g is None and not morning and not note:
        raise EntryError("nothing to log: give at least one of --tendon, --legs, --startup-pain, --hip, --fuel, --note")

    activity_id = None
    if activity is not None:
        row = resolve_activity(conn, activity, day)
        activity_id = row["id"]
        if not morning:
            day = date.fromisoformat(row["start_time_local"][:10])

    cursor = conn.execute(
        "INSERT INTO manual_entries"
        " (date, activity_id, tendon_pain, startup_pain, legs, hip_pain, fuel_g, note, created_at)"
        " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            day.isoformat(),
            activity_id,
            tendon,
            int(startup_pain) if morning else None,
            LEGS_ALIASES[legs] if legs else None,
            int(hip_pain) if morning else None,
            fuel_g,
            note,
            datetime.now().isoformat(timespec="seconds"),
        ),
    )
    conn.commit()
    return cursor.lastrowid
