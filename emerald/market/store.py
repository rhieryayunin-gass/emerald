from __future__ import annotations

from collections import deque
from datetime import timedelta
from threading import RLock

from .ticks import TickQuote


class TickStore:
    """Thread-safe, bounded tick history separated by broker and symbol."""

    def __init__(self, max_ticks: int = 20_000, max_age: timedelta | None = None) -> None:
        if max_ticks < 2:
            raise ValueError("max_ticks must be at least 2")
        self._max_ticks = max_ticks
        self._max_age = max_age or timedelta(minutes=30)
        self._windows: dict[tuple[str, str], deque[TickQuote]] = {}
        self._lock = RLock()

    @staticmethod
    def _key(broker_id: str, symbol: str) -> tuple[str, str]:
        broker = broker_id.strip().casefold()
        normalized_symbol = symbol.strip().upper()
        if not broker:
            raise ValueError("broker_id cannot be empty")
        if not normalized_symbol:
            raise ValueError("symbol cannot be empty")
        return broker, normalized_symbol

    def append_many(self, broker_id: str, ticks: list[TickQuote]) -> int:
        if not ticks:
            return 0
        symbols = {tick.symbol.strip().upper() for tick in ticks}
        if len(symbols) != 1:
            raise ValueError("one batch must contain exactly one symbol")
        ordered = sorted(ticks, key=lambda tick: (tick.broker_time, tick.observed_at))
        if ordered != ticks:
            raise ValueError("ticks must be ordered by broker_time")

        key = self._key(broker_id, ordered[0].symbol)
        accepted = 0
        with self._lock:
            window = self._windows.setdefault(key, deque(maxlen=self._max_ticks))
            existing = {
                (tick.broker_time, tick.bid, tick.ask, tick.volume)
                for tick in window
            }
            for tick in ordered:
                if window and tick.broker_time < window[-1].broker_time:
                    signature = (tick.broker_time, tick.bid, tick.ask, tick.volume)
                    if signature in existing:
                        continue
                    raise ValueError("tick is older than the latest stored broker_time")
                signature = (tick.broker_time, tick.bid, tick.ask, tick.volume)
                if signature in existing:
                    continue
                window.append(tick)
                existing.add(signature)
                accepted += 1
            self._prune(window)
        return accepted

    def snapshot(self, broker_id: str, symbol: str) -> tuple[TickQuote, ...]:
        key = self._key(broker_id, symbol)
        with self._lock:
            window = self._windows.get(key)
            return tuple(window) if window else ()

    def clear(self) -> None:
        with self._lock:
            self._windows.clear()

    def stream_statuses(self) -> list[dict[str, object]]:
        """Return safe metadata only; never copy full tick windows to observability."""
        with self._lock:
            statuses = [
                {
                    "broker_id": broker_id,
                    "symbol": symbol,
                    "stored_ticks": len(window),
                    "latest_bid": window[-1].bid,
                    "latest_ask": window[-1].ask,
                    "latest_broker_time": window[-1].broker_time,
                    "latest_observed_at": window[-1].observed_at,
                }
                for (broker_id, symbol), window in self._windows.items()
                if window
            ]
        return sorted(statuses, key=lambda item: (str(item["broker_id"]), str(item["symbol"])))

    def _prune(self, window: deque[TickQuote]) -> None:
        if not window:
            return
        cutoff = window[-1].broker_time - self._max_age
        while window and window[0].broker_time < cutoff:
            window.popleft()
