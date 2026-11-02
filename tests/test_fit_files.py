import io
import zipfile
from datetime import UTC, datetime, timedelta

import pytest

from runlog.sources.fit_files import VO2MAX_FIELD, VO2MAX_MESSAGE, extract_fit, parse_messages

T0 = datetime(2026, 1, 1, 8, 0, tzinfo=UTC)


def record(seconds, **fields):
    return ("record", {"timestamp": T0 + timedelta(seconds=seconds), **fields})


def test_samples_offsets_and_running_cadence():
    data = parse_messages(
        [
            ("session", {"sport": "running"}),
            record(0, heart_rate=120, enhanced_speed=3.0, cadence=85, fractional_cadence=0.5),
            record(1, heart_rate=121, speed=3.1, cadence=86),
        ]
    )
    assert [s["t_offset_s"] for s in data.samples] == [0, 1]
    assert data.samples[0]["cadence_spm"] == 171.0
    assert data.samples[1]["speed"] == 3.1
    assert data.samples[1]["cadence_spm"] == 172.0


def test_cadence_not_doubled_for_other_sports():
    data = parse_messages([("session", {"sport": "cycling"}), record(0, cadence=90)])
    assert data.samples[0]["cadence_spm"] is None


def test_duplicate_timestamps_keep_last():
    data = parse_messages([record(0, heart_rate=100), record(0, heart_rate=101)])
    assert len(data.samples) == 1
    assert data.samples[0]["hr"] == 101


def test_no_gps_in_samples():
    data = parse_messages([record(0, position_lat=1, position_long=2)])
    assert not any("position" in key for key in data.samples[0])


def test_laps():
    data = parse_messages(
        [
            ("session", {"sport": "running"}),
            (
                "lap",
                {"total_distance": 1000.0, "total_timer_time": 300.0, "avg_running_cadence": 85, "intensity": "active"},
            ),
            ("lap", {"total_distance": 1000.0, "total_timer_time": 290.0}),
        ]
    )
    assert [lap["lap_index"] for lap in data.laps] == [0, 1]
    assert data.laps[0]["avg_cadence_spm"] == 170.0
    assert data.laps[0]["intensity"] == "active"


@pytest.mark.parametrize(("raw", "expected"), [(round(50.0 / 3.5 * 65536), 50.0), (1, None), (None, None)])
def test_vo2max(raw, expected):
    data = parse_messages([(VO2MAX_MESSAGE, {VO2MAX_FIELD: raw})])
    assert data.vo2max == expected


def test_extract_fit_from_zip_and_plain():
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("123_ACTIVITY.fit", b"fitdata")
    assert extract_fit(buffer.getvalue()) == b"fitdata"
    assert extract_fit(b"plain") == b"plain"
