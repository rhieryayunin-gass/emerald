from datetime import UTC, datetime, timedelta

from emerald.fundamental import CalendarEvent, EconomicCalendarClient
from emerald.strategies import StrategyClassifier


def healthy_context(event: CalendarEvent | None = None) -> dict[str, object]:
    return {"source_health": "HEALTHY", "matched_event": event.evidence() if event else None}


def test_high_impact_usd_news_has_priority_over_clock_window() -> None:
    classifier = StrategyClassifier(morning_start_minute=240, morning_end_minute=300)
    event_time = datetime(2026, 9, 8, 20, 15, tzinfo=UTC)
    event = CalendarEvent("event", "CPI", "USD", "High", event_time, None, None, None, "test")
    mode, evidence = classifier.classify(event_time=event_time, news_context=healthy_context(event))
    assert mode == "NEWS_REVERSAL"
    assert evidence["classification"] == "HIGH_IMPACT_USD_NEWS"


def test_daily_0400_to_0500_wib_is_rollover_not_monday_only() -> None:
    classifier = StrategyClassifier(morning_start_minute=240, morning_end_minute=300)
    friday_0415_wib = datetime(2026, 9, 11, 21, 15, tzinfo=UTC)
    mode, evidence = classifier.classify(event_time=friday_0415_wib, news_context=healthy_context())
    assert mode == "ROLLOVER_REVERSAL"
    assert evidence["classification"] == "DAILY_MORNING_ROLLOVER"


def test_calendar_context_matches_only_high_impact_usd_window() -> None:
    client = EconomicCalendarClient(url="https://calendar.invalid", refresh_seconds=300, timeout_seconds=1)
    scheduled = datetime(2026, 9, 8, 12, 30, tzinfo=UTC)
    client._events = (CalendarEvent("cpi", "CPI", "USD", "High", scheduled, "3.0%", "2.9%", "2.8%", "test"),)
    client._last_refresh = datetime.now(UTC)
    matched = client.context_for(scheduled + timedelta(minutes=20), before_minutes=10, after_minutes=45)
    outside = client.context_for(scheduled + timedelta(minutes=46), before_minutes=10, after_minutes=45)
    assert matched["matched_event"] is not None
    assert outside["matched_event"] is None
