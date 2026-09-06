from datetime import UTC, datetime, timedelta

from emerald.detectors import MismatchDetector
from emerald.domain import TradeSide
from emerald.market import TickQuote

NOW = datetime(2026, 9, 2, tzinfo=UTC)


def quote(index: int, bid: float, ask: float) -> TickQuote:
    timestamp = NOW + timedelta(seconds=index)
    return TickQuote("XAUUSD", bid, ask, timestamp, timestamp)


def stable_baseline() -> list[TickQuote]:
    bids = [2500.00, 2500.01, 2500.00, 2499.99, 2500.00, 2500.01, 2500.00, 2499.99]
    return [quote(index, bid, bid + 0.20) for index, bid in enumerate(bids)]


def test_detects_confirmed_down_spike_and_buy_reclaim() -> None:
    ticks = stable_baseline()
    ticks.extend(
        [
            quote(8, 2490.00, 2490.20),
            quote(9, 2492.00, 2492.20),
            quote(10, 2495.00, 2495.20),
            quote(11, 2497.00, 2497.20),
            quote(12, 2498.00, 2498.20),
            quote(13, 2498.50, 2498.70),
        ]
    )
    result = MismatchDetector().detect(tuple(ticks), point=0.01)
    assert result.candidate is not None
    assert result.candidate.direction is TradeSide.BUY
    assert result.candidate.reversal_confirmed is True
    assert result.candidate.spread_artifact is False
    assert result.candidate.detector_score == 1.0
    assert result.reasons == ("CANDIDATE_CONFIRMED",)
    assert result.candidate.confirmed_at == ticks[-1].broker_time
    assert result.candidate.entry_reference == ticks[-1].ask


def test_detects_confirmed_up_spike_and_sell_reclaim() -> None:
    ticks = stable_baseline()
    ticks.extend(
        [
            quote(8, 2510.00, 2510.20),
            quote(9, 2508.00, 2508.20),
            quote(10, 2505.00, 2505.20),
            quote(11, 2503.00, 2503.20),
            quote(12, 2502.00, 2502.20),
            quote(13, 2501.50, 2501.70),
        ]
    )
    result = MismatchDetector().detect(tuple(ticks), point=0.01)
    assert result.candidate is not None
    assert result.candidate.direction is TradeSide.SELL
    assert result.candidate.reversal_confirmed is True
    assert result.candidate.structural_invalidation > result.candidate.extreme_price


def test_rejects_spread_only_false_spike() -> None:
    ticks = stable_baseline()
    ticks.extend(
        [
            quote(8, 2480.00, 2500.20),
            quote(9, 2488.00, 2500.20),
            quote(10, 2492.00, 2500.20),
            quote(11, 2496.00, 2500.20),
            quote(12, 2498.00, 2500.20),
            quote(13, 2499.00, 2500.20),
        ]
    )
    result = MismatchDetector().detect(tuple(ticks), point=0.01)
    assert result.candidate is not None
    assert result.candidate.spread_artifact is True
    assert result.candidate.reversal_confirmed is False
    assert "SPREAD_ONLY_ARTIFACT" in result.reasons


def test_requires_enough_ticks() -> None:
    result = MismatchDetector().detect(tuple(stable_baseline()), point=0.01)
    assert result.candidate is None
    assert result.reasons == ("INSUFFICIENT_TICKS",)


def test_rejects_entry_after_structural_target_was_already_reclaimed() -> None:
    ticks = stable_baseline()
    ticks.extend(
        [
            quote(8, 2490.00, 2490.20),
            quote(9, 2492.00, 2492.20),
            quote(10, 2495.00, 2495.20),
            quote(11, 2499.80, 2500.00),
            quote(12, 2500.00, 2500.20),
            quote(13, 2500.20, 2500.40),
        ]
    )
    result = MismatchDetector().detect(tuple(ticks), point=0.01)
    assert result.candidate is not None
    assert result.candidate.reversal_confirmed is False
    assert "STRUCTURAL_TARGET_ALREADY_RECLAIMED" in result.reasons
