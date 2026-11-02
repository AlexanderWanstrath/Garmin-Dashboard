"""Interface every data source implements, so sync does not depend on Garmin specifics."""

from __future__ import annotations

from datetime import date
from typing import Any, Protocol


class Source(Protocol):
    name: str

    def list_activities(self, since: date | None) -> list[dict[str, Any]]:
        """Activity summaries starting on or after `since` (all if None)."""

    def activity_detail(self, activity_id: int) -> dict[str, Any] | None: ...

    def activity_file(self, activity_id: int) -> bytes | None:
        """The original FIT file (possibly zipped), or None if unavailable."""

    def daily_summaries(self, start: date, end: date) -> Any: ...

    def hrv(self, start: date, end: date) -> Any: ...

    def sleep(self, start: date, end: date) -> Any: ...

    def heart_rate_zones(self) -> Any: ...
