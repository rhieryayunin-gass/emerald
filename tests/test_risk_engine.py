import math
from dataclasses import replace

import pytest

from emerald.domain import (
    AccountTradeMode,
    DecisionAction,
    DecisionStatus,
    StrategyMode,
    SystemState,
    TradeSide,
)
from emerald.risk import HardRiskEngine, tier_lot_ceiling

from .fixtures import valid_context, valid_proposal


def test_rejects_non_finite_numeric_input() -> None:
    approval = HardRiskEngine().evaluate(
        valid_proposal(calibrated_probability=math.nan),
        valid_context(),
    )
    assert approval.approved is False
    assert "NON_FINITE_NUMERIC_INPUT" in approval.reasons


@pytest.mark.parametrize(
    ("equity", "expected"),
    [
        (0.0, 0.01),
        (499.99, 0.01),
        (500.0, 0.02),
        (999.99, 0.02),
        (1000.0, 0.03),
        (24_500.0, 0.50),
        (100_000.0, 0.50),
    ],
)
def test_locked_tier_lot(equity: float, expected: float) -> None:
    assert tier_lot_ceiling(equity) == expected


def test_valid_demo_trade_is_approved() -> None:
    result = HardRiskEngine().evaluate(valid_proposal(), valid_context())
    assert result.approved is True
    assert result.status is DecisionStatus.APPROVED
    assert result.approved_lot == 0.03
    assert result.projected_loss_fraction == pytest.approx(0.0186)


def test_probability_below_80_is_rejected() -> None:
    result = HardRiskEngine().evaluate(
        valid_proposal(calibrated_probability=0.7999), valid_context()
    )
    assert result.approved is False
    assert "PROBABILITY_BELOW_80_PERCENT" in result.reasons


def test_special_setup_risk_is_reduced_to_five_percent() -> None:
    proposal = valid_proposal(
        strategy_mode=StrategyMode.NEWS_REVERSAL,
        requested_risk_fraction=0.08,
    )
    result = HardRiskEngine().evaluate(proposal, valid_context())
    assert result.approved is True
    assert result.status is DecisionStatus.REDUCED
    assert result.approved_risk_fraction == 0.05


def test_aggregate_open_risk_reduces_remaining_capacity() -> None:
    context = valid_context(current_open_risk_fraction=0.08)
    result = HardRiskEngine().evaluate(valid_proposal(requested_risk_fraction=0.05), context)
    assert result.approved is True
    assert result.status is DecisionStatus.REDUCED
    assert result.approved_risk_fraction == pytest.approx(0.02)


def test_daily_loss_hard_stop_blocks_entry() -> None:
    context = valid_context(daily_realized_pnl=-200.0)
    result = HardRiskEngine().evaluate(valid_proposal(), context)
    assert result.approved is False
    assert "DAILY_LOSS_HARD_STOP" in result.reasons


def test_overall_drawdown_hard_stop_blocks_entry() -> None:
    context = valid_context(equity_high_water_mark=2000.0, current_equity=1000.0)
    result = HardRiskEngine().evaluate(valid_proposal(), context)
    assert result.approved is False
    assert "OVERALL_DRAWDOWN_HARD_STOP" in result.reasons


def test_real_account_is_rejected_by_default() -> None:
    base = valid_context()
    real_execution = replace(base.execution, account_trade_mode=AccountTradeMode.REAL)
    result = HardRiskEngine().evaluate(valid_proposal(), replace(base, execution=real_execution))
    assert result.approved is False
    assert "REAL_ACCOUNT_NOT_AUTHORIZED" in result.reasons


def test_fail_safe_state_blocks_entry() -> None:
    context = replace(valid_context(), system_state=SystemState.FAIL_SAFE)
    result = HardRiskEngine().evaluate(valid_proposal(), context)
    assert result.approved is False
    assert "SYSTEM_STATE_FAIL_SAFE_BLOCKS_ENTRY" in result.reasons


def test_sixth_tranche_is_rejected() -> None:
    proposal = valid_proposal(tranche_number=6, is_existing_thesis=True)
    result = HardRiskEngine().evaluate(proposal, valid_context())
    assert result.approved is False
    assert "INVALID_TRANCHE_NUMBER" in result.reasons


def test_minimum_lot_is_rejected_when_stop_risk_is_too_large() -> None:
    proposal = valid_proposal(
        requested_risk_fraction=0.01,
        requested_lot=0.50,
        structural_invalidation=2400.0,
    )
    context = valid_context()
    context = replace(
        context,
        pattern=replace(context.pattern, structural_invalidation=2400.0),
    )
    result = HardRiskEngine().evaluate(proposal, context)
    assert result.approved is False
    assert "LOT_BELOW_BROKER_MINIMUM" in result.reasons


def test_ai_cannot_change_detector_invalidation() -> None:
    result = HardRiskEngine().evaluate(
        valid_proposal(structural_invalidation=2490.0), valid_context()
    )
    assert result.approved is False
    assert "INVALIDATION_CONFLICTS_WITH_PATTERN" in result.reasons


def test_entry_action_must_match_direction() -> None:
    proposal = valid_proposal(
        action=DecisionAction.ENTER_SELL,
        direction=TradeSide.BUY,
    )
    result = HardRiskEngine().evaluate(proposal, valid_context())
    assert result.approved is False
    assert "ENTRY_ACTION_DIRECTION_CONFLICT" in result.reasons
