"""SQLite access: connection, numbered migrations and small upsert helpers."""

from __future__ import annotations

import sqlite3
from collections.abc import Iterable, Mapping
from importlib import resources
from pathlib import Path
from typing import Any


def connect(path: str | Path) -> sqlite3.Connection:
    """Open the database and bring the schema up to date.

    The default rollback journal is kept (no WAL) so read-only connections work reliably.
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    migrate(conn)
    return conn


def migrations() -> list[tuple[int, str]]:
    """Migration files as (number, sql), sorted by number. Names look like 001_initial.sql."""
    files = resources.files("runlog") / "migrations"
    found = [
        (int(f.name.split("_", 1)[0]), f.read_text(encoding="utf-8"))
        for f in files.iterdir()
        if f.name.endswith(".sql")
    ]
    return sorted(found)


def migrate(conn: sqlite3.Connection) -> None:
    """Apply all migrations newer than PRAGMA user_version, each in its own transaction."""
    current = conn.execute("PRAGMA user_version").fetchone()[0]
    for number, sql in migrations():
        if number <= current:
            continue
        try:
            conn.executescript(f"BEGIN;\n{sql}\nPRAGMA user_version = {number};\nCOMMIT;")
        except sqlite3.Error:
            conn.rollback()
            raise


def upsert(conn: sqlite3.Connection, table: str, row: Mapping[str, Any], key: Iterable[str]) -> None:
    """Insert row, or update only the given columns if the key already exists."""
    key = list(key)
    cols = list(row)
    updates = [c for c in cols if c not in key]
    sql = f"INSERT INTO {table} ({', '.join(cols)}) VALUES ({', '.join('?' * len(cols))})"
    if updates:
        sql += f" ON CONFLICT ({', '.join(key)}) DO UPDATE SET " + ", ".join(f"{c} = excluded.{c}" for c in updates)
    else:
        sql += " ON CONFLICT DO NOTHING"
    conn.execute(sql, [row[c] for c in cols])


def replace_rows(conn: sqlite3.Connection, table: str, activity_id: int, rows: list[Mapping[str, Any]]) -> None:
    """Replace all rows of an activity in a child table (samples, laps)."""
    conn.execute(f"DELETE FROM {table} WHERE activity_id = ?", (activity_id,))
    if not rows:
        return
    cols = list(rows[0])
    conn.executemany(
        f"INSERT INTO {table} ({', '.join(cols)}) VALUES ({', '.join('?' * len(cols))})",
        [[r.get(c) for c in cols] for r in rows],
    )


def get_state(conn: sqlite3.Connection, name: str) -> str | None:
    row = conn.execute("SELECT value FROM sync_state WHERE name = ?", (name,)).fetchone()
    return row[0] if row else None


def set_state(conn: sqlite3.Connection, name: str, value: str) -> None:
    upsert(conn, "sync_state", {"name": name, "value": value}, key=["name"])
