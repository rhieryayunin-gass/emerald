from datetime import UTC, datetime

from emerald.domain import (
    AccountTradeMode,
    DataFreshness,
    DecisionAction,
    DecisionContext,
    ExecutionSnapshot,
    FundamentalSnapshot,
    MarketSnapshot,
    PatternSnapshot,
    RiskSnapshot,
    StatisticsSnapshot,
    StrategyMode,
    SystemState,
    TradeProposal,
    TradeSide,
)

NOW = datetime(2026, 9, 2, tzinfo=UTC)


def valid_context(**risk_overrides: object) -> DecisionContext:
    risk_values = {
        "observed_at": NOW,
        "start_of_day_equity": 1000.0,
        "equity_high_water_mark": 1100.0,
        "current_equity": 1000.0,
        "current_open_risk_fraction": 0.0,
        "active_theses": 0,
        "daily_realized_pnl": 0.0,
        "daily_unrealized_pnl": 0.0,
    }
    risk_values.update(risk_overrides)
    return DecisionContext(
        market=MarketSnapshot(
            symbol="XAUUSD",
            bid=2500.00,
            ask=2500.20,
            point=0.01,
            digits=2,
            spread_points=20.0,
            broker_time=NOW,
            observed_at=NOW,
            session="NEW_YORK",
        ),
        statistics=StatisticsSnapshot(
            observed_at=NOW,
            atr_m1=2.0,
            atr_m5=5.0,
            displacement_zscore=3.1,
            recovery_probability=0.86,
            expected_reward=8.0,
            expected_loss=3.0,
            expected_slippage=0.2,
            calibration_sample_size=250,
        ),
        fundamental=FundamentalSnapshot(
            observed_at=NOW,
            feed_healthy=True,
            high_impact_event_active=False,
        ),
        pattern=PatternSnapshot(
            observed_at=NOW,
            mismatch_class="LIQUIDITY_SWEEP",
            reversal_confirmed=True,
            direction=TradeSide.BUY,
            displacement_origin=2508.0,
            structural_target=2508.0,
            structural_invalidation=2494.0,
            evidence=("reclaim", "momentum_shift"),
        ),
        execution=ExecutionSnapshot(
            observed_at=NOW,
            account_trade_mode=AccountTradeMode.DEMO,
            hedging_enabled=True,
            equity=1000.0,
            balance=1000.0,
            free_margin=900.0,
            margin_level=1000.0,
            current_total_lot=0.0,
            broker_min_lot=0.01,
            broker_max_lot=100.0,
            broker_lot_step=0.01,
            tick_size=0.01,
            tick_value_loss_per_lot=1.0,
        ),
        risk=RiskSnapshot(**risk_values),
        freshness=DataFreshness(
            market_age_seconds=0.2,
            statistics_age_seconds=1.0,
            fundamental_age_seconds=1.0,
            pattern_age_seconds=0.2,
            execution_age_seconds=0.2,
            risk_age_seconds=0.2,
        ),
        system_state=SystemState.COLD_START,
        evaluated_at=NOW,
    )


def valid_proposal(**overrides: object) -> TradeProposal:
    values = {
        "decision_id": "decision-1",
        "setup_id": "setup-1",
        "thesis_id": "thesis-1",
        "strategy_mode": StrategyMode.REGULAR_MISMATCH,
        "action": DecisionAction.ENTER_BUY,
        "direction": TradeSide.BUY,
        "calibrated_probability": 0.86,
        "expected_value_net": 3.5,
        "requested_risk_fraction": 0.03,
        "requested_lot": 0.03,
        "structural_target": 2508.0,
        "structural_invalidation": 2494.0,
        "tranche_number": 1,
        "is_existing_thesis": False,
        "reason_summary": ("confirmed liquidity sweep",),
    }
    values.update(overrides)
    return TradeProposal(**values)
