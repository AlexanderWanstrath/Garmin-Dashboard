"""Garmin Personal API source. The only module that touches the API key."""

from __future__ import annotations

import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from datetime import date
from typing import Any, TypeVar

from garmin_personal_api import GarminPersonalApiClient, HttpError, PersonalApiAuthenticator, resolve_api_key

T = TypeVar("T")

PAGE_SIZE = 100
RETRY_STATUS = {429, 500, 502, 503, 504}


class AuthError(Exception):
    """The API key is missing, invalid or expired."""


class GarminSource:
    name = "garmin"

    def __init__(self, client: GarminPersonalApiClient, retries: int = 3, backoff_s: float = 2.0) -> None:
        self.client = client
        self.retries = retries
        self.backoff_s = backoff_s

    @classmethod
    @contextmanager
    def open(cls) -> Iterator[GarminSource]:
        try:
            with PersonalApiAuthenticator() as authenticator:
                token = authenticator.obtain_token(resolve_api_key())
        except HttpError as exc:
            raise AuthError(
                f"Garmin rejected the API key (HTTP {exc.status_code}). It may have expired: "
                "create a new key and store it in ~/.config/garmin/connect-personal-api-key."
            ) from exc
        except Exception as exc:
            raise AuthError(
                f"No usable Garmin API key ({type(exc).__name__}). Set GARMIN_PERSONAL_API_KEY "
                "or store the key in ~/.config/garmin/connect-personal-api-key."
            ) from exc
        with GarminPersonalApiClient(token.access_token) as client:
            yield cls(client)

    def _call(self, fn: Callable[[], T]) -> T:
        """Retry rate limits and server errors with exponential backoff."""
        for attempt in range(self.retries + 1):
            try:
                return fn()
            except HttpError as exc:
                if exc.status_code not in RETRY_STATUS or attempt == self.retries:
                    raise
                time.sleep(self.backoff_s * 2**attempt)
        raise AssertionError("unreachable")

    def list_activities(self, since: date | None) -> list[dict[str, Any]]:
        activities: list[dict[str, Any]] = []
        while True:
            kwargs: dict[str, Any] = {"start": len(activities), "limit": PAGE_SIZE}
            if since is not None:
                kwargs.update(start_date=since, end_date=date.today())
            page = self._call(lambda kw=kwargs: self.client.search_activities(**kw))
            if not isinstance(page, list):
                return activities
            activities.extend(a for a in page if isinstance(a, dict))
            if len(page) < PAGE_SIZE:
                return activities

    def activity_detail(self, activity_id: int) -> dict[str, Any] | None:
        result = self._call(lambda: self.client.get_activity(activity_id))
        return result if isinstance(result, dict) else None

    def activity_file(self, activity_id: int) -> bytes | None:
        try:
            return self._call(lambda: self.client.download_activity(activity_id))
        except HttpError as exc:
            if exc.status_code == 404:
                return None
            raise

    def daily_summaries(self, start: date, end: date) -> Any:
        return self._call(lambda: self.client.get_daily_summaries(start, end))

    def hrv(self, start: date, end: date) -> Any:
        return self._call(lambda: self.client.get_daily_hrv_summaries(start, end))

    def sleep(self, start: date, end: date) -> Any:
        return self._call(lambda: self.client.get_daily_sleep_summaries(start, end))

    def heart_rate_zones(self) -> Any:
        return self._call(self.client.get_heart_rate_zones)
