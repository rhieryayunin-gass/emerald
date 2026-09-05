from datetime import UTC, datetime, timedelta

import pytest

from emerald.market import TickQuote, TickStore

NOW = datetime(2026, 9, 2, tzinfo=UTC)


def tick(second: int, bid: float = 2500.0, ask: float = 2500.2) -> TickQuote:
    timestamp = NOW + timedelta(seconds=second)
    return TickQuote("XAUUSD", bid, ask, timestamp, timestamp)


def test_store_separates_brokers_and_deduplicates_last_tick() -> None:
    store = TickStore()
    quote = tick(0)
    assert store.append_many("broker-a", [quote, quote]) == 1
    assert store.append_many("broker-b", [quote]) == 1
    assert len(store.snapshot("broker-a", "xauusd")) == 1
    assert len(store.snapshot("broker-b", "XAUUSD")) == 1


def test_store_accepts_overlapping_retry_without_duplication() -> None:
    store = TickStore()
    batch = [tick(0), tick(1), tick(2)]
    assert store.append_many("broker-a", batch) == 3
    assert store.append_many("broker-a", batch) == 0
    assert len(store.snapshot("broker-a", "XAUUSD")) == 3


def test_store_exposes_stream_metadata_without_tick_payloads() -> None:
    store = TickStore()
    store.append_many("Broker-A", [tick(0), tick(1)])
    statuses = store.stream_statuses()
    assert statuses == [
        {
            "broker_id": "broker-a",
            "symbol": "XAUUSD",
            "stored_ticks": 2,
            "latest_bid": tick(1).bid,
            "latest_ask": tick(1).ask,
            "latest_broker_time": tick(1).broker_time,
            "latest_observed_at": tick(1).observed_at,
        }
    ]


def test_store_rejects_out_of_order_batch() -> None:
    store = TickStore()
    with pytest.raises(ValueError, match="ordered"):
        store.append_many("broker-a", [tick(2), tick(1)])


def test_store_prunes_old_ticks() -> None:
    store = TickStore(max_age=timedelta(seconds=5))
    store.append_many("broker-a", [tick(0), tick(10)])
    assert store.snapshot("broker-a", "XAUUSD") == (tick(10),)


def test_tick_requires_timezone_and_valid_bid_ask() -> None:
    naive = NOW.replace(tzinfo=None)
    with pytest.raises(ValueError, match="timezone-aware"):
        TickQuote("XAUUSD", 2500.0, 2500.2, naive, naive)
    with pytest.raises(ValueError, match="ask"):
        TickQuote("XAUUSD", 2500.2, 2500.0, NOW, NOW)
