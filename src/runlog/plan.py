"""Training plan: load plan.yaml and compare planned sessions with what was actually run."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta
from pathlib import Path
from typing import Any

import yaml

from runlog.metrics import Row, activity_date, is_run, week_start
from runlog.metrics.intensity import share_above

TYPES = {"E": "easy", "L": "long run", "Q": "quality", "R": "race/test", "T": "pacing"}
MATCH_WINDOW_DAYS = 2  # sessions may be swapped with nearby days
KM_TOLERANCE = 0.15  # more than 15 % off the planned distance is reported


class PlanError(Exception):
    """plan.yaml is missing or malformed."""


@dataclass
class Session:
    date: date
    type: str
    name: str
    km: tuple[float, float] | None = None
    pace_s: tuple[float, float] | None = None  # fastest, slowest in s/km
    hr_max: float | None = None
    reps: int | None = None
    rep_pace_s: tuple[float, float] | None = None
    fuel_g_per_h: float | None = None


@dataclass
class PlanWeek:
    start: date
    km: tuple[float, float]
    label: str | None = None


@dataclass
class Plan:
    weeks: list[PlanWeek]
    sessions: list[Session]


@dataclass
class SessionResult:
    session: Session
    status: str  # "done", "moved", "missed", "upcoming"
    activity_id: int | None = None
    actual_date: date | None = None
    actual_km: float | None = None
    findings: list[str] = field(default_factory=list)  # deviations from the plan, empty = as planned


@dataclass
class WeekResult:
    week: PlanWeek
    actual_km: float
    status: str  # "below", "within", "above", "in progress"


def parse_pace(value: Any) -> float:
    """'4:05' -> 245 seconds per km."""
    minutes, seconds = str(value).split(":")
    return int(minutes) * 60 + float(seconds)


def format_pace(seconds: float) -> str:
    seconds = round(seconds)
    return f"{seconds // 60}:{seconds % 60:02d}"


def _range(value: Any, parse=float) -> tuple[float, float] | None:
    if value is None:
        return None
    if isinstance(value, list | tuple):
        low, high = (parse(v) for v in value)
        return (min(low, high), max(low, high))
    return (parse(value), parse(value))


def _date(value: Any) -> date:
    return value if isinstance(value, date) else date.fromisoformat(str(value))


def load_plan(path: str | Path) -> Plan:
    path = Path(path)
    if not path.exists():
        raise PlanError(f"{path} not found: copy plan.example.yaml to {path.name} and enter your plan")
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        sessions = []
        for s in raw.get("sessions") or []:
            reps = s.get("reps") or {}
            if s["type"] not in TYPES:
                raise PlanError(f"{path}: unknown session type {s['type']!r} on {s['date']}")
            sessions.append(
                Session(
                    date=_date(s["date"]),
                    type=s["type"],
                    name=s.get("name") or TYPES[s["type"]],
                    km=_range(s.get("km")),
                    pace_s=_range(s.get("pace"), parse_pace),
                    hr_max=s.get("hr_max"),
                    reps=reps.get("count"),
                    rep_pace_s=_range(reps.get("pace"), parse_pace),
                    fuel_g_per_h=s.get("fuel_g_per_h"),
                )
            )
        weeks = [PlanWeek(_date(w["start"]), _range(w["km"]), w.get("label")) for w in raw.get("weeks") or []]
    except (KeyError, TypeError, ValueError, yaml.YAMLError) as exc:
        raise PlanError(f"{path} is malformed: {exc}") from exc
    return Plan(weeks=sorted(weeks, key=lambda w: w.start), sessions=sorted(sessions, key=lambda s: s.date))


def match_sessions(plan: Plan, activities: list[Row], today: date) -> dict[int, Row]:
    """Assign runs to planned sessions: same day first, then the closest day within the window.

    Returns {session index: activity}. A run is used for at most one session; on a day with
    several runs the longest one counts. Runs before the plan's first week are ignored, and a
    session from today on only matches a run on its own day (it may still be run later).
    """
    if not plan.sessions:
        return {}
    plan_start = week_start(plan.sessions[0].date)
    runs = sorted(
        (a for a in activities if is_run(a) and activity_date(a) >= plan_start),
        key=lambda a: -(a.get("distance_m") or 0),
    )
    used: set[int] = set()
    matches: dict[int, Row] = {}
    for offset in range(MATCH_WINDOW_DAYS + 1):
        for i, session in enumerate(plan.sessions):
            if i in matches or session.date > today or (session.date == today and offset):
                continue
            for a in runs:
                if a["id"] in used or abs((activity_date(a) - session.date).days) != offset:
                    continue
                matches[i] = a
                used.add(a["id"])
                break
    return matches


def evaluate(
    plan: Plan,
    activities: list[Row],
    today: date,
    samples_for: Any = None,
    laps_for: Any = None,
    fuel_for: Any = None,
    over_cap_share: float = 0.1,
    rep_tolerance_s: float = 2,
) -> list[SessionResult]:
    """Compare every planned session up to today with the matching run.

    samples_for, laps_for and fuel_for are callables taking an activity id, so the caller
    decides how data is loaded (database in production, lists in tests).
    """
    matches = match_sessions(plan, activities, today)
    results = []
    for i, session in enumerate(plan.sessions):
        activity = matches.get(i)
        if activity is None:
            # Today's session may still be run later in the day.
            status = "upcoming" if session.date >= today else "missed"
            results.append(SessionResult(session, status))
            continue
        actual_date = activity_date(activity)
        result = SessionResult(
            session,
            "done" if actual_date == session.date else "moved",
            activity_id=activity["id"],
            actual_date=actual_date,
            actual_km=round((activity.get("distance_m") or 0) / 1000, 1),
        )
        result.findings += check_distance(session, result.actual_km)
        if session.type in ("E", "L"):
            result.findings += check_easy(session, activity, samples_for, over_cap_share)
        if session.type == "Q" and laps_for:
            result.findings += check_reps(session, laps_for(activity["id"]), rep_tolerance_s)
        if session.type in ("R", "T") and session.pace_s and laps_for:
            result.findings += check_main_pace(session, laps_for(activity["id"]))
        if session.fuel_g_per_h and fuel_for:
            result.findings += check_fuel(session, activity, fuel_for(activity["id"]))
        results.append(result)
    return results


def check_distance(session: Session, actual_km: float | None) -> list[str]:
    if not session.km or actual_km is None:
        return []
    low, high = session.km
    if actual_km < low * (1 - KM_TOLERANCE):
        return [f"shorter than planned: {actual_km} km instead of {_km(session.km)}"]
    if actual_km > high * (1 + KM_TOLERANCE):
        return [f"longer than planned: {actual_km} km instead of {_km(session.km)}"]
    return []


def check_easy(session: Session, activity: Row, samples_for: Any, over_cap_share: float) -> list[str]:
    findings = []
    speed = activity.get("avg_moving_speed") or activity.get("avg_speed")
    if session.pace_s and speed:
        pace = 1000 / speed
        if pace < session.pace_s[0]:
            findings.append(f"too fast: {format_pace(pace)}/km, cap {format_pace(session.pace_s[0])}/km")
    if session.hr_max and samples_for:
        share = share_above(samples_for(activity["id"]), session.hr_max)
        if share is not None and share > over_cap_share:
            findings.append(f"{share:.0%} of moving time above {session.hr_max:.0f} bpm")
    elif session.hr_max and (activity.get("avg_hr") or 0) > session.hr_max:
        findings.append(f"average HR {activity['avg_hr']:.0f} above {session.hr_max:.0f} bpm")
    return findings


def rep_paces(laps: list[Row]) -> list[float]:
    """Pace in s/km of the work intervals, i.e. laps the watch workout marks as active."""
    return [1000 / lap["avg_speed"] for lap in laps if lap.get("intensity") == "active" and lap.get("avg_speed")]


def check_reps(session: Session, laps: list[Row], tolerance_s: float) -> list[str]:
    paces = rep_paces(laps)
    if not paces:
        return ["no work intervals found (run without a watch workout?)"]
    findings = []
    if session.reps and len(paces) != session.reps:
        findings.append(f"{len(paces)} work intervals instead of {session.reps}")
    if session.rep_pace_s:
        fastest_allowed = session.rep_pace_s[0] - tolerance_s
        too_fast = [i for i, p in enumerate(paces, 1) if p < fastest_allowed]
        if too_fast:
            listed = ", ".join(f"#{i} {format_pace(paces[i - 1])}" for i in too_fast)
            findings.append(f"faster than {format_pace(session.rep_pace_s[0])}/km: {listed}")
        if paces[0] < fastest_allowed:
            findings.append("first rep faster than the plan's fastest pace")
    if len(paces) > 1 and min(paces) == paces[-1] and paces[-1] < paces[0]:
        findings.append("last rep was the fastest")
    return findings


def check_main_pace(session: Session, laps: list[Row]) -> list[str]:
    """Races and pacing runs: mean pace of the active laps against the planned range."""
    active = [lap for lap in laps if lap.get("intensity") == "active" and lap.get("distance_m") and lap.get("timer_s")]
    if not active or not session.pace_s:
        return []
    pace = sum(lap["timer_s"] for lap in active) / sum(lap["distance_m"] for lap in active) * 1000
    low, high = session.pace_s
    if pace < low - 2:
        return [f"main part {format_pace(pace)}/km, faster than planned {format_pace(low)}/km"]
    if pace > high + 2:
        return [f"main part {format_pace(pace)}/km, slower than planned {format_pace(high)}/km"]
    return []


def check_fuel(session: Session, activity: Row, fuel_g: float | None) -> list[str]:
    hours = (activity.get("duration_s") or 0) / 3600
    if fuel_g is None:
        return [f"no fueling logged (target {session.fuel_g_per_h:.0f} g/h)"]
    if not hours:
        return []
    per_hour = fuel_g / hours
    if per_hour < session.fuel_g_per_h * 0.9:
        return [f"fueling {per_hour:.0f} g/h, target {session.fuel_g_per_h:.0f} g/h"]
    return []


def weekly_status(plan: Plan, activities: list[Row], today: date) -> list[WeekResult]:
    km_by_week: dict[date, float] = {}
    for a in activities:
        if is_run(a):
            start = week_start(activity_date(a))
            km_by_week[start] = km_by_week.get(start, 0) + (a.get("distance_m") or 0) / 1000
    results = []
    for week in plan.weeks:
        if week.start > today:
            continue
        actual = round(km_by_week.get(week.start, 0), 1)
        low, high = week.km
        if today < week.start + timedelta(days=7):
            status = "in progress"
        elif actual < low * (1 - KM_TOLERANCE / 2):
            status = "below"
        elif actual > high * (1 + KM_TOLERANCE / 2):
            status = "above"
        else:
            status = "within"
        results.append(WeekResult(week, actual, status))
    return results


def _km(value: tuple[float, float]) -> str:
    low, high = value
    return f"{low:g} km" if low == high else f"{low:g}-{high:g} km"
