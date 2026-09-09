"""Fail-closed economic-calendar adapter for shadow classification."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import UTC, datetime, timedelta
from typing import Any
from urllib.request import Request, urlopen


@dataclass(frozen=True)
class CalendarEvent:
    event_id: str
    title: str
    currency: str
    impact: str
    scheduled_at: datetime
    actual: str | None
    forecast: str | None
    previous: str | None
    source: str

    def evidence(self) -> dict[str, object]:
        return {**asdict(self), "scheduled_at": self.scheduled_at.isoformat()}


class EconomicCalendarClient:
    """Cache a public calendar feed so tick ingestion never fetches per tick."""

    def __init__(self, *, url: str, refresh_seconds: int, timeout_seconds: float) -> None:
        self.url = url
        self.refresh_seconds = refresh_seconds
        self.timeout_seconds = timeout_seconds
        self._events: tuple[CalendarEvent, ...] = ()
        self._last_refresh: datetime | None = None
        self._last_error: str | None = None

    def context_for(self, at: datetime, *, before_minutes: int, after_minutes: int) -> dict[str, object]:
        self._refresh_if_due()
        event = next(
            (
                item for item in self._events
                if item.currency == "USD" and item.impact == "High"
                and item.scheduled_at - timedelta(minutes=before_minutes) <= at
                <= item.scheduled_at + timedelta(minutes=after_minutes)
            ),
            None,
        )
        return {
            "source_health": "HEALTHY" if self._last_error is None else "UNAVAILABLE",
            "source": self.url,
            "fetched_at": self._last_refresh.isoformat() if self._last_refresh else None,
            "fresh": self._last_refresh is not None
            and datetime.now(UTC) - self._last_refresh <= timedelta(seconds=self.refresh_seconds * 2),
            "error": self._last_error,
            "matched_event": event.evidence() if event else None,
        }

    def _refresh_if_due(self) -> None:
        now = datetime.now(UTC)
        if self._last_refresh and now - self._last_refresh < timedelta(seconds=self.refresh_seconds):
            return
        try:
            request = Request(self.url, headers={"User-Agent": "RIRI-EMERALD/0.3 shadow-calendar"})
            with urlopen(request, timeout=self.timeout_seconds) as response:
                payload: Any = json.loads(response.read().decode("utf-8"))
            self._events = tuple(self._parse(payload))
            self._last_error = None
        except (OSError, ValueError, TypeError, KeyError) as error:
            self._last_error = type(error).__name__
        finally:
            self._last_refresh = now

    @staticmethod
    def _parse(payload: Any) -> list[CalendarEvent]:
        if not isinstance(payload, list):
            raise TypeError("calendar payload must be a list")
        events: list[CalendarEvent] = []
        for row in payload:
            if not isinstance(row, dict) or row.get("country") != "USD" or row.get("impact") != "High":
                continue
            scheduled_at = datetime.fromisoformat(str(row["date"])).astimezone(UTC)
            title = str(row.get("title", "Unknown event"))
            events.append(CalendarEvent(
                event_id=f"ff:{scheduled_at.isoformat()}:{title}", title=title,
                currency="USD", impact="High", scheduled_at=scheduled_at,
                actual=row.get("actual"), forecast=row.get("forecast"), previous=row.get("previous"),
                source="forexfactory-calendar",
            ))
        return events
