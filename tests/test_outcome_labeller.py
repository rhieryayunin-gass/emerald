from datetime import UTC, datetime, timedelta

import pytest

from emerald.domain import TradeSide
from emerald.evaluation import ShadowOutcomeLabeller
from emerald.market import TickQuote

NOW = datetime(2026, 9, 2, tzinfo=UTC)


def quote(seconds: int, bid: float, ask: float) -> TickQuote:
    timestamp = NOW + timedelta(seconds=seconds)
    return TickQuote("XAUUSD", bid, ask, timestamp, timestamp)


def test_buy_target_uses_executable_bid_after_confirmation() -> None:
    result = ShadowOutcomeLabeller().evaluate(
        event_id="buy-1",
        direction=TradeSide.BUY,
        confirmed_at=NOW,
        entry_reference=2498.20,
        structural_target=2500.00,
        structural_invalidation=2490.00,
        point=0.01,
        ticks=(quote(1, 2499.80, 2500.00), quote(2, 2500.10, 2500.30)),
    )
    assert result is not None
    assert result.outcome == "TARGET_HIT"
    assert result.pricing_side == "BID"
    assert result.exit_price == 2500.10
    assert result.duration_seconds == 2.0
    assert result.r_multiple > 0


def test_sell_target_uses_executable_ask_after_confirmation() -> None:
    result = ShadowOutcomeLabeller().evaluate(
        event_id="sell-1",
        direction=TradeSide.SELL,
        confirmed_at=NOW,
        entry_reference=2502.00,
        structural_target=2500.00,
        structural_invalidation=2510.00,
        point=0.01,
        ticks=(quote(3, 2499.70, 2499.90),),
    )
    assert result is not None
    assert result.outcome == "TARGET_HIT"
    assert result.pricing_side == "ASK"
    assert result.exit_price == 2499.90


def test_stop_hit_is_negative_and_preconfirmation_ticks_are_ignored() -> None:
    result = ShadowOutcomeLabeller().evaluate(
        event_id="buy-stop",
        direction=TradeSide.BUY,
        confirmed_at=NOW + timedelta(seconds=5),
        entry_reference=2498.20,
        structural_target=2500.00,
        structural_invalidation=2490.00,
        point=0.01,
        ticks=(quote(1, 2480.00, 2480.20), quote(6, 2489.90, 2490.10)),
    )
    assert result is not None
    assert result.outcome == "STOP_HIT"
    assert result.pnl_points < 0
    assert result.r_multiple < 0


def test_returns_none_while_neither_boundary_is_hit() -> None:
    result = ShadowOutcomeLabeller().evaluate(
        event_id="open-1",
        direction=TradeSide.BUY,
        confirmed_at=NOW,
        entry_reference=2498.20,
        structural_target=2500.00,
        structural_invalidation=2490.00,
        point=0.01,
        ticks=(quote(1, 2498.30, 2498.50),),
    )
    assert result is None


def test_rejects_invalid_structure() -> None:
    with pytest.raises(ValueError, match="BUY structure"):
        ShadowOutcomeLabeller().evaluate(
            event_id="bad-1",
            direction=TradeSide.BUY,
            confirmed_at=NOW,
            entry_reference=2501.00,
            structural_target=2500.00,
            structural_invalidation=2490.00,
            point=0.01,
            ticks=(),
        )
