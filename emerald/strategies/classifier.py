from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

from emerald.domain import StrategyMode

JAKARTA = ZoneInfo("Asia/Jakarta")


class StrategyClassifier:
    def __init__(self, *, morning_start_minute: int, morning_end_minute: int) -> None:
        self.morning_start_minute = morning_start_minute
        self.morning_end_minute = morning_end_minute

    def classify(self, *, event_time: datetime, news_context: dict[str, object]) -> tuple[StrategyMode, dict[str, object]]:
        event = news_context.get("matched_event")
        released = False
        if isinstance(event, dict):
            try:
                scheduled_at = datetime.fromisoformat(str(event["scheduled_at"]))
                released = (
                    scheduled_at.tzinfo is not None and scheduled_at <= event_time
                    and event.get("currency") == "USD" and event.get("impact") == "High"
                )
            except (KeyError, ValueError, TypeError):
                pass
        if released and news_context.get("fresh") is True and news_context.get("source_health") == "HEALTHY":
            return StrategyMode.NEWS_REVERSAL, {"classification": "HIGH_IMPACT_USD_NEWS", "news": news_context}
        jakarta_time = event_time.astimezone(JAKARTA)
        minute = jakarta_time.hour * 60 + jakarta_time.minute
        if self.morning_start_minute <= minute < self.morning_end_minute:
            return StrategyMode.ROLLOVER_REVERSAL, {
                "classification": "DAILY_MORNING_ROLLOVER", "jakarta_time": jakarta_time.isoformat(),
                "window": f"{self.morning_start_minute // 60:02d}:{self.morning_start_minute % 60:02d}-"
                f"{self.morning_end_minute // 60:02d}:{self.morning_end_minute % 60:02d} WIB",
                "news": news_context,
            }
        return StrategyMode.REGULAR_MISMATCH, {"classification": "REGULAR_MISMATCH", "jakarta_time": jakarta_time.isoformat(), "news": news_context}
