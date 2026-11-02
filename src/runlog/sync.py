"""Incremental sync from a source into the local database."""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

from runlog import db, normalize
from runlog.sources.base import Source
from runlog.sources.fit_files import extract_fit, parse_fit

HEALTH_CHUNK_DAYS = 28
# Garmin fills in recent days later (sleep, HRV, end-of-day totals), so they are fetched again.
HEALTH_REFETCH_DAYS = 3
ACTIVITY_OVERLAP_DAYS = 1
FIRST_SYNC_FALLBACK_DAYS = 30


@dataclass
class SyncResult:
    new_activities: int = 0
    known_activities: int = 0
    health_days: int = 0
    health_range: tuple[date, date] | None = None
    warnings: list[str] = field(default_factory=list)


def run_sync(
    conn: sqlite3.Connection,
    source: Source,
    data_dir: Path,
    *,
    today: date | None = None,
    start_date: date | None = None,
    log: Callable[[str], None] = print,
) -> SyncResult:
    today = today or date.today()
    result = SyncResult()
    sync_activities(conn, source, data_dir, result, start_date, log)
    sync_health(conn, source, result, today, start_date, log)
    store_raw(conn, f"{source.name}/heart_rate_zones", today.isoformat(), source.heart_rate_zones())
    db.set_state(conn, "last_sync", _now())
    conn.commit()
    return result


def sync_activities(
    conn: sqlite3.Connection,
    source: Source,
    data_dir: Path,
    result: SyncResult,
    start_date: date | None,
    log: Callable[[str], None],
) -> None:
    latest = conn.execute("SELECT max(start_time_local) FROM activities").fetchone()[0]
    since = date.fromisoformat(latest[:10]) - timedelta(days=ACTIVITY_OVERLAP_DAYS) if latest else start_date
    log(f"Activities: searching {'since ' + since.isoformat() if since else 'full history'}")

    known = {row[0] for row in conn.execute("SELECT id FROM activities")}
    listed = source.list_activities(since)
    new = sorted((a for a in listed if a.get("activityId") not in known), key=lambda a: a.get("startTimeLocal", ""))
    result.known_activities = len(listed) - len(new)

    for i, summary in enumerate(new, 1):
        activity_id = summary["activityId"]
        day = summary.get("startTimeLocal", "")[:10]
        log(f"  [{i}/{len(new)}] {day} {normalize.get(summary, 'activityType.typeKey')}")
        detail = source.activity_detail(activity_id)
        store_raw(conn, f"{source.name}/activity_summary", str(activity_id), summary)
        store_raw(conn, f"{source.name}/activity_detail", str(activity_id), detail)

        row = normalize.activity_row(summary, detail)
        row["synced_at"] = _now()
        fit = None
        content = source.activity_file(activity_id)
        if content is None:
            result.warnings.append(f"activity {activity_id}: no FIT file available")
        else:
            row["fit_path"] = str(save_fit(data_dir, activity_id, content))
            try:
                fit = parse_fit(content)
            except Exception as exc:
                result.warnings.append(f"activity {activity_id}: FIT file could not be parsed ({type(exc).__name__})")
        if fit is not None:
            row["vo2max"] = fit.vo2max
            if fit.vo2max is None and row["type"] and "running" in row["type"]:
                result.warnings.append(f"activity {activity_id}: run without VO2max in FIT file")

        db.upsert(conn, "activities", row, key=["id"])
        if fit is not None:
            db.replace_rows(
                conn, "activity_samples", activity_id, [{"activity_id": activity_id, **s} for s in fit.samples]
            )
            db.replace_rows(conn, "laps", activity_id, [{"activity_id": activity_id, **lap} for lap in fit.laps])
        conn.commit()  # one activity at a time, so an interrupted sync keeps what it has
        result.new_activities += 1


def sync_health(
    conn: sqlite3.Connection,
    source: Source,
    result: SyncResult,
    today: date,
    start_date: date | None,
    log: Callable[[str], None],
) -> None:
    until = db.get_state(conn, "daily_health_until")
    if until:
        start = date.fromisoformat(until) - timedelta(days=HEALTH_REFETCH_DAYS)
    elif start_date:
        start = start_date
    else:
        first = conn.execute("SELECT min(start_time_local) FROM activities").fetchone()[0]
        start = date.fromisoformat(first[:10]) if first else today - timedelta(days=FIRST_SYNC_FALLBACK_DAYS)
    log(f"Health data: {start.isoformat()} to {today.isoformat()}")

    days = 0
    chunk_start = start
    while chunk_start <= today:
        chunk_end = min(chunk_start + timedelta(days=HEALTH_CHUNK_DAYS - 1), today)
        key = f"{chunk_start.isoformat()}/{chunk_end.isoformat()}"
        summaries = source.daily_summaries(chunk_start, chunk_end)
        hrv = source.hrv(chunk_start, chunk_end)
        sleep = source.sleep(chunk_start, chunk_end)
        for endpoint, data in (("daily_summaries", summaries), ("hrv", hrv), ("sleep", sleep)):
            store_raw(conn, f"{source.name}/{endpoint}", key, data)

        rows = normalize.merge_daily(
            normalize.daily_summary_rows(summaries), normalize.hrv_rows(hrv), normalize.sleep_rows(sleep)
        )
        for day, row in rows.items():
            db.upsert(conn, "daily_health", {"date": day, **row, "updated_at": _now()}, key=["date"])
        days += len(rows)
        conn.commit()
        chunk_start = chunk_end + timedelta(days=1)

    db.set_state(conn, "daily_health_until", today.isoformat())
    result.health_days = days
    result.health_range = (start, today)


def store_raw(conn: sqlite3.Connection, endpoint: str, key: str, data: Any) -> None:
    if data is None:
        return
    db.upsert(
        conn,
        "raw_responses",
        {"endpoint": endpoint, "key": key, "fetched_at": _now(), "json": json.dumps(data, default=str)},
        key=["endpoint", "key"],
    )


def save_fit(data_dir: Path, activity_id: int, content: bytes) -> Path:
    path = data_dir / "fit" / f"{activity_id}.fit"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(extract_fit(content))
    return path


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")
