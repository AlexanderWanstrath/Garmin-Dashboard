"""Read Garmin FIT files: per-second samples, laps and VO2max.

Reading (fitdecode) and interpretation are split, so the interpretation can be
tested with plain dicts instead of binary FIT files.
"""

from __future__ import annotations

import io
import zipfile
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

# A FIT data message as (message name, {field name or number: value}).
Message = tuple[str, dict[Any, Any]]

# Undocumented Garmin message holding VO2max in field 7 as VO2max * 65536 / 3.5
# (community reverse engineering; agrees with Garmin Connect to within rounding).
VO2MAX_MESSAGE = "unknown_140"
VO2MAX_FIELD = 7
VO2MAX_SCALE = 3.5 / 65536
VO2MAX_PLAUSIBLE = (10.0, 100.0)


@dataclass
class FitData:
    samples: list[dict[str, Any]] = field(default_factory=list)
    laps: list[dict[str, Any]] = field(default_factory=list)
    vo2max: float | None = None


def extract_fit(content: bytes) -> bytes:
    """Return the FIT file from a Garmin download, which is a ZIP with one .fit inside."""
    if not zipfile.is_zipfile(io.BytesIO(content)):
        return content
    with zipfile.ZipFile(io.BytesIO(content)) as archive:
        names = [n for n in archive.namelist() if n.lower().endswith(".fit")]
        if not names:
            raise ValueError("download contains no .fit file")
        return archive.read(names[0])


def read_messages(fit: bytes) -> list[Message]:
    """Decode the data messages needed here. Unknown messages are keyed by field number."""
    import fitdecode

    wanted = {"record", "lap", "session", VO2MAX_MESSAGE}
    messages: list[Message] = []
    with fitdecode.FitReader(io.BytesIO(fit)) as reader:
        for frame in reader:
            if not isinstance(frame, fitdecode.FitDataMessage) or frame.name not in wanted:
                continue
            fields: dict[Any, Any] = {}
            for f in frame.fields:
                key, value = (f.def_num, f.raw_value) if frame.name.startswith("unknown_") else (f.name, f.value)
                # A field can appear twice (e.g. enhanced_avg_speed expanded from an empty avg_speed);
                # an empty duplicate must not overwrite the real value.
                if value is not None or key not in fields:
                    fields[key] = value
            messages.append((frame.name, fields))
    return messages


def parse_messages(messages: list[Message]) -> FitData:
    data = FitData()
    sport = next((str(f.get("sport")) for name, f in messages if name == "session" and f.get("sport")), "")
    running = sport == "running"
    start: datetime | None = None

    for name, f in messages:
        if name == "record":
            ts = f.get("timestamp")
            if not isinstance(ts, datetime):
                continue
            start = start or ts
            data.samples.append(
                {
                    "t_offset_s": int((ts - start).total_seconds()),
                    "hr": f.get("heart_rate"),
                    "speed": _first(f, "enhanced_speed", "speed"),
                    "distance_m": f.get("distance"),
                    "altitude_m": _first(f, "enhanced_altitude", "altitude"),
                    "cadence_spm": _cadence_spm(f.get("cadence"), f.get("fractional_cadence"), running),
                    "power_w": f.get("power"),
                    "temperature_c": f.get("temperature"),
                    "step_length_mm": f.get("step_length"),
                    "vertical_oscillation_mm": f.get("vertical_oscillation"),
                    "vertical_ratio_pct": f.get("vertical_ratio"),
                    "stance_time_ms": f.get("stance_time"),
                }
            )
        elif name == "lap":
            start_time = f.get("start_time")
            data.laps.append(
                {
                    "lap_index": len(data.laps),
                    "start_time": start_time.isoformat() if isinstance(start_time, datetime) else None,
                    "distance_m": f.get("total_distance"),
                    "timer_s": f.get("total_timer_time"),
                    "elapsed_s": f.get("total_elapsed_time"),
                    "avg_hr": f.get("avg_heart_rate"),
                    "max_hr": f.get("max_heart_rate"),
                    "avg_speed": _first(f, "enhanced_avg_speed", "avg_speed"),
                    "max_speed": _first(f, "enhanced_max_speed", "max_speed"),
                    "avg_cadence_spm": _cadence_spm(
                        _first(f, "avg_running_cadence", "avg_cadence"), f.get("avg_fractional_cadence"), running
                    ),
                    "avg_power_w": f.get("avg_power"),
                    "norm_power_w": f.get("normalized_power"),
                    "ascent_m": f.get("total_ascent"),
                    "descent_m": f.get("total_descent"),
                    "calories_kcal": f.get("total_calories"),
                    "intensity": _str(f.get("intensity")),
                    "lap_trigger": _str(f.get("lap_trigger")),
                }
            )
        elif name == VO2MAX_MESSAGE and data.vo2max is None:
            data.vo2max = _vo2max(f.get(VO2MAX_FIELD))

    # Records can repeat a timestamp; keep the last one per second.
    data.samples = list({s["t_offset_s"]: s for s in data.samples}.values())
    return data


def parse_fit(content: bytes) -> FitData:
    return parse_messages(read_messages(extract_fit(content)))


def _first(fields: dict[Any, Any], *names: str) -> Any:
    return next((fields[n] for n in names if fields.get(n) is not None), None)


def _cadence_spm(cadence: Any, fractional: Any, running: bool) -> float | None:
    """FIT stores running cadence per leg (strides/min); steps/min counts both legs."""
    if cadence is None or not running:
        return None
    return round((cadence + (fractional or 0)) * 2, 1)


def _vo2max(raw: Any) -> float | None:
    if not isinstance(raw, int | float):
        return None
    value = round(raw * VO2MAX_SCALE, 1)
    low, high = VO2MAX_PLAUSIBLE
    return value if low <= value <= high else None


def _str(value: Any) -> str | None:
    return None if value is None else str(value)
