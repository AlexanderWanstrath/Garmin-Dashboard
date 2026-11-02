"""Stage 0: check which training data the Garmin Personal API returns.

The script only prints whether data and fields are present. It never prints
measured values, so the report can be shared safely. With --save-raw, the raw
JSON responses are additionally written to a local folder for later schema
design. That folder contains personal health data: do not share or commit it.

Requirements:
    python -m pip install garmin-connect-personal-api-python
    (optional, for the FIT check) python -m pip install fitdecode

Key: set the environment variable GARMIN_PERSONAL_API_KEY or store the key in
~/.config/garmin/connect-personal-api-key. Never pass it on the command line.

Usage:
    python scripts/stage0_check.py
    python scripts/stage0_check.py --days 60 --save-raw
"""

from __future__ import annotations

import argparse
import io
import json
import zipfile
from collections.abc import Callable
from datetime import date, timedelta
from pathlib import Path
from typing import Any

from garmin_personal_api import (
    GarminPersonalApiClient,
    GarminPersonalApiError,
    HttpError,
    PersonalApiAuthenticator,
    resolve_api_key,
)

OK, MISSING, FAIL = "OK  ", "--  ", "FAIL"

# Fields we expect to need for the dashboard, per data set.
RUN_SUMMARY_FIELDS = [
    "activityId",
    "startTimeLocal",
    "activityType",
    "distance",
    "duration",
    "movingDuration",
    "averageSpeed",
    "averageHR",
    "maxHR",
    "elevationGain",
    "averageRunningCadenceInStepsPerMinute",
    "hrTimeInZone_1",
    "hrTimeInZone_2",
    "hrTimeInZone_3",
    "hrTimeInZone_4",
    "hrTimeInZone_5",
    "aerobicTrainingEffect",
    "anaerobicTrainingEffect",
    "trainingEffectLabel",
    "vO2MaxValue",
]

# Field name fragments (lower case) for contact data and exact positions.
# They are replaced before raw data is written to disk; names are kept.
REDACT_FRAGMENTS = ("email", "latitude", "longitude")
REDACTED = "<redacted>"


def redact(obj: Any) -> Any:
    """Copy of obj with names and coordinates replaced, at any nesting depth."""
    if isinstance(obj, dict):
        return {
            k: REDACTED if any(f in k.lower() for f in REDACT_FRAGMENTS) and v is not None else redact(v)
            for k, v in obj.items()
        }
    if isinstance(obj, list):
        return [redact(x) for x in obj]
    return obj


class Report:
    def __init__(self) -> None:
        self.lines: list[str] = []

    def section(self, title: str) -> None:
        self.lines.append(f"\n## {title}")

    def add(self, status: str, label: str, detail: str = "") -> None:
        self.lines.append(f"[{status}] {label}" + (f": {detail}" if detail else ""))

    def text(self) -> str:
        return "\n".join(self.lines).strip()


def keys_of(obj: Any) -> list[str]:
    if isinstance(obj, dict):
        return sorted(obj.keys())
    if isinstance(obj, list) and obj and isinstance(obj[0], dict):
        return sorted(obj[0].keys())
    return []


def non_empty_keys(obj: Any) -> list[str]:
    """Top-level keys whose value is not None, empty or zero-length."""
    if isinstance(obj, list):
        obj = next((x for x in obj if isinstance(x, dict)), {})
    if not isinstance(obj, dict):
        return []
    return sorted(k for k, v in obj.items() if v not in (None, "", [], {}))


def nested_fields(obj: Any) -> str:
    """Top-level fields plus the fields of nested lists of objects, without values."""
    if isinstance(obj, list):
        obj = next((x for x in obj if isinstance(x, dict)), {})
    if not isinstance(obj, dict):
        return ""
    parts = []
    for key in non_empty_keys(obj):
        value = obj[key]
        if isinstance(value, list) and value and isinstance(value[0], dict):
            parts.append(f"{key}[{len(value)}]: {{{', '.join(non_empty_keys(value[0]))}}}")
        elif isinstance(value, dict):
            parts.append(f"{key}: {{{', '.join(non_empty_keys(value))}}}")
        else:
            parts.append(key)
    return ", ".join(parts)


def describe(obj: Any) -> str:
    if obj is None:
        return "empty response"
    if isinstance(obj, list):
        return f"list with {len(obj)} entries"
    if isinstance(obj, dict):
        return f"object with {len(obj)} fields"
    return type(obj).__name__


def call(report: Report, label: str, fn: Callable[[], Any], raw: dict[str, Any]) -> Any:
    try:
        result = fn()
    except HttpError as exc:
        report.add(FAIL, label, f"HTTP {exc.status_code}")
        return None
    except GarminPersonalApiError as exc:
        report.add(FAIL, label, type(exc).__name__)
        return None
    except Exception as exc:  # network or JSON errors
        report.add(FAIL, label, type(exc).__name__)
        return None
    raw[label] = result
    status = OK if result not in (None, [], {}) else MISSING
    report.add(status, label, describe(result))
    return result


def check_fit(report: Report, content: bytes) -> None:
    try:
        archive = zipfile.ZipFile(io.BytesIO(content))
    except zipfile.BadZipFile:
        report.add(FAIL, "FIT archive", "not a ZIP file")
        return
    fit_names = [n for n in archive.namelist() if n.lower().endswith(".fit")]
    report.add(OK if fit_names else MISSING, "FIT file in ZIP", f"{len(fit_names)} file(s)")
    if not fit_names:
        return
    try:
        import fitdecode  # type: ignore
    except ImportError:
        report.add(MISSING, "FIT content", "install fitdecode to inspect records and laps")
        return

    counts = {"record": 0, "record_hr": 0, "record_speed": 0, "lap": 0, "hrv": 0, "vo2max": 0}
    data = archive.read(fit_names[0])
    try:
        _count_fit(fitdecode, data, counts)
    except Exception as exc:
        report.add(FAIL, "FIT content", f"could not be parsed ({type(exc).__name__})")
        return
    report.add(OK if counts["record"] else MISSING, "FIT per-second records", str(counts["record"]))
    report.add(OK if counts["record_hr"] else MISSING, "FIT records with heart rate", str(counts["record_hr"]))
    report.add(OK if counts["record_speed"] else MISSING, "FIT records with speed", str(counts["record_speed"]))
    report.add(OK if counts["lap"] else MISSING, "FIT laps (km splits)", str(counts["lap"]))
    report.add(OK if counts["hrv"] else MISSING, "FIT beat-to-beat HRV messages", str(counts["hrv"]))
    report.add(OK if counts["vo2max"] else MISSING, "FIT VO2max (message 140, field 7)", str(counts["vo2max"]))


def _count_fit(fitdecode: Any, data: bytes, counts: dict[str, int]) -> None:
    with fitdecode.FitReader(io.BytesIO(data)) as reader:
        for frame in reader:
            if not isinstance(frame, fitdecode.FitDataMessage):
                continue
            if frame.name == "record":
                counts["record"] += 1
                if frame.has_field("heart_rate") and frame.get_value("heart_rate") is not None:
                    counts["record_hr"] += 1
                if any(frame.has_field(f) for f in ("enhanced_speed", "speed")):
                    counts["record_speed"] += 1
            elif frame.name == "lap":
                counts["lap"] += 1
            elif frame.name == "hrv":
                counts["hrv"] += 1
            # Undocumented Garmin message; field 7 holds VO2max * 65536 / 3.5 (community reverse engineering).
            elif frame.name == "unknown_140" and frame.has_field(7) and frame.get_value(7) is not None:
                counts["vo2max"] += 1


def search_all(client: GarminPersonalApiClient, start: date, end: date, page_size: int = 100) -> list[Any]:
    """Page through the activity search until a short page signals the end."""
    activities: list[Any] = []
    while True:
        page = client.search_activities(
            start=len(activities),
            limit=page_size,
            start_date=start.isoformat(),
            end_date=end.isoformat(),
        )
        if not isinstance(page, list):
            return activities
        activities.extend(page)
        if len(page) < page_size:
            return activities


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--days", type=int, default=30, help="look-back window for activities and wellness data")
    parser.add_argument("--save-raw", action="store_true", help="save raw JSON locally (personal data, do not share)")
    parser.add_argument("--raw-dir", default="raw_stage0", help="folder for --save-raw")
    args = parser.parse_args()

    today = date.today()
    start = today - timedelta(days=args.days)
    week_start = today - timedelta(days=7)
    report = Report()
    raw: dict[str, Any] = {}

    report.section("Authentication")
    try:
        with PersonalApiAuthenticator() as authenticator:
            token = authenticator.obtain_token(resolve_api_key())
    except Exception as exc:
        status = f"HTTP {exc.status_code}" if isinstance(exc, HttpError) else type(exc).__name__
        report.add(FAIL, "Token", f"{status}: check that the key is set and not expired")
        print(report.text())
        return
    report.add(OK, "Token", "obtained")

    with GarminPersonalApiClient(token.access_token) as client:
        report.section(f"Activities (last {args.days} days)")
        activities = (
            call(
                report,
                "activity search",
                lambda: search_all(client, start, today),
                raw,
            )
            or []
        )
        runs = (
            [a for a in activities if "running" in str((a.get("activityType") or {}).get("typeKey", ""))]
            if isinstance(activities, list)
            else []
        )
        # Do not rely on the API's sort order: the latest run is checked in detail.
        runs.sort(key=lambda a: str(a.get("startTimeLocal", "")), reverse=True)
        report.add(OK if runs else MISSING, "running activities", f"{len(runs)} of {len(activities)}")

        if runs:
            present = set(non_empty_keys(runs[0]))
            found = [f for f in RUN_SUMMARY_FIELDS if f in present]
            missing = [f for f in RUN_SUMMARY_FIELDS if f not in present]
            report.add(OK, "expected run fields present", ", ".join(found) or "none")
            if missing:
                report.add(MISSING, "expected run fields missing", ", ".join(missing))
            report.add(OK, "all run summary fields", ", ".join(non_empty_keys(runs[0])))
            # The latest run may not be typical (treadmill, no GPS): count coverage over all runs.
            per_run = [set(non_empty_keys(r)) for r in runs]
            partial = [
                f"{f} {n}/{len(runs)}" for f in RUN_SUMMARY_FIELDS if (n := sum(f in p for p in per_run)) < len(runs)
            ]
            report.add(
                OK if not partial else MISSING,
                "expected run fields not in every run",
                ", ".join(partial) or "none",
            )

            run_id = runs[0]["activityId"]
            report.section("Latest run: details")
            detail = call(report, "activity details", lambda: client.get_activity(run_id), raw)
            if isinstance(detail, dict):
                report.add(OK, "detail fields", ", ".join(non_empty_keys(detail)))
                summary = detail.get("summaryDTO")
                if isinstance(summary, dict):
                    report.add(OK, "summaryDTO fields", ", ".join(non_empty_keys(summary)))
            call(report, "activity workouts", lambda: client.get_activity_workouts(run_id), raw)
            for label, path in [
                ("splits endpoint (no wrapper)", f"/activity-service/activity/{run_id}/splits"),
                ("split summaries endpoint (no wrapper)", f"/activity-service/activity/{run_id}/split_summaries"),
                ("hr zones endpoint (no wrapper)", f"/activity-service/activity/{run_id}/hrTimeInZones"),
            ]:
                result = call(report, label, lambda p=path: client.get(p), raw)
                if result:
                    report.add(OK, f"{label} fields", nested_fields(result))

            report.section("Latest run: FIT file")
            try:
                content = client.download_activity(run_id)
                report.add(OK, "FIT download", f"{len(content) // 1024} KB")
                check_fit(report, content)
            except Exception as exc:
                status = f"HTTP {exc.status_code}" if isinstance(exc, HttpError) else type(exc).__name__
                report.add(FAIL, "FIT download", status)

        report.section("History reach")
        # Several windows, so a hard API limit can be told apart from a gap in the data.
        for lo, hi in [(30, 60), (60, 90), (90, 180), (180, 365), (365, 730)]:
            call(
                report,
                f"activities {lo}-{hi} days ago",
                lambda lo=lo, hi=hi: search_all(client, today - timedelta(days=hi), today - timedelta(days=lo)),
                raw,
            )
        # Paging without a date filter shows how far back the list goes at all.
        try:
            undated: list[Any] = []
            while len(undated) < 2000:
                page = client.search_activities(start=len(undated), limit=100)
                if not isinstance(page, list) or not page:
                    break
                undated.extend(page)
                if len(page) < 100:
                    break
            dates = sorted(str(a.get("startTimeLocal", ""))[:10] for a in undated if a.get("startTimeLocal"))
            age = (today - date.fromisoformat(dates[0])).days if dates else 0
            report.add(
                OK if age > 90 else MISSING,
                "activity list without date filter",
                f"{len(undated)} activities, oldest {age} days ago",
            )
        except Exception as exc:
            status = f"HTTP {exc.status_code}" if isinstance(exc, HttpError) else type(exc).__name__
            report.add(FAIL, "activity list without date filter", status)

        report.section("VO2max")
        for label, fn in [
            ("max metrics (no wrapper)", lambda: client.get(f"/metrics-service/metrics/maxmet/daily/{start}/{today}")),
            ("max metrics latest (no wrapper)", lambda: client.get(f"/metrics-service/metrics/maxmet/latest/{today}")),
            ("fitness age", lambda: client.get_fitness_age(today)),
        ]:
            result = call(report, label, fn, raw)
            if result:
                report.add(OK, f"{label} fields", nested_fields(result))

        report.section("Health data (last 7 days)")
        hrv = call(report, "HRV summaries", lambda: client.get_daily_hrv_summaries(week_start, today), raw)
        if hrv:
            report.add(OK, "HRV fields", nested_fields(hrv))
        call(report, "HRV single day (yesterday)", lambda: client.get_daily_hrv(today - timedelta(days=1)), raw)
        hr = call(
            report, "daily heart rate (yesterday)", lambda: client.get_daily_heart_rate(today - timedelta(days=1)), raw
        )
        if isinstance(hr, dict):
            report.add(
                OK if hr.get("restingHeartRate") is not None else MISSING, "resting heart rate in daily heart rate"
            )
        summaries = call(report, "daily summaries", lambda: client.get_daily_summaries(week_start, today), raw)
        if summaries:
            # The entries sit in a "data" wrapper; resting heart rate may be nested inside "heartRate".
            entries = summaries.get("data", summaries) if isinstance(summaries, dict) else summaries
            fields = nested_fields(entries)
            has_rhr = "restingHeartRate" in fields or "restingValue" in fields
            report.add(OK if has_rhr else MISSING, "resting heart rate in daily summaries")
            report.add(OK, "daily summary fields", fields)
        sleep = call(report, "sleep summaries", lambda: client.get_daily_sleep_summaries(week_start, today), raw)
        if sleep:
            report.add(OK, "sleep fields", nested_fields(sleep))
        call(report, "body battery", lambda: client.get_daily_body_battery(week_start, today), raw)
        call(report, "stress", lambda: client.get_daily_stress(week_start, today), raw)

        report.section("Profile")
        zones = call(report, "heart rate zones", client.get_heart_rate_zones, raw)
        if zones:
            report.add(OK, "zone fields", nested_fields(zones))

    print(report.text())
    print("\nThe report above contains no measured values and can be shared.")

    if args.save_raw:
        out = Path(args.raw_dir)
        out.mkdir(exist_ok=True)
        for label, data in raw.items():
            name = "".join(c if c.isalnum() else "_" for c in label).strip("_")
            (out / f"{name}.json").write_text(json.dumps(redact(data), indent=2, default=str), encoding="utf-8")
        print(f"Raw responses saved to {out.resolve()} (email and coordinates redacted; still personal data).")


if __name__ == "__main__":
    main()
