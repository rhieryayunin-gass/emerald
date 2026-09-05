from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from .enums import (
    AccountTradeMode,
    DecisionAction,
    DecisionStatus,
    StrategyMode,
    SystemState,
    TradeSide,
)


def utc_now() -> datetime:
    return datetime.now(UTC)


@dataclass(frozen=True, slots=True)
class MarketSnapshot:
    symbol: str
    bid: float
    ask: float
    point: float
    digits: int
    spread_points: float
    broker_time: datetime
    observed_at: datetime
    session: str
    tradeable: bool = True

    def __post_init__(self) -> None:
        if self.ask < self.bid:
            raise ValueError("ask must be greater than or equal to bid")
        if self.point <= 0:
            raise ValueError("point must be positive")


@dataclass(frozen=True, slots=True)
class StatisticsSnapshot:
    observed_at: datetime
    atr_m1: float
    atr_m5: float
    displacement_zscore: float
    recovery_probability: float
    expected_reward: float
    expected_loss: float
    expected_slippage: float
    calibration_sample_size: int


@dataclass(frozen=True, slots=True)
class FundamentalSnapshot:
    observed_at: datetime
    feed_healthy: bool
    high_impact_event_active: bool
    event_id: str | None = None
    event_name: str | None = None
    minutes_to_event: float | None = None


@dataclass(frozen=True, slots=True)
class PatternSnapshot:
    observed_at: datetime
    mismatch_class: str
    reversal_confirmed: bool
    direction: TradeSide
    displacement_origin: float
    structural_target: float
    structural_invalidation: float
    evidence: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class ExecutionSnapshot:
    observed_at: datetime
    account_trade_mode: AccountTradeMode
    hedging_enabled: bool
    equity: float
    balance: float
    free_margin: float
    margin_level: float
    current_total_lot: float
    broker_min_lot: float
    broker_max_lot: float
    broker_lot_step: float
    tick_size: float
    tick_value_loss_per_lot: float
    terminal_connected: bool = True
    trade_allowed: bool = True


@dataclass(frozen=True, slots=True)
class RiskSnapshot:
    observed_at: datetime
    start_of_day_equity: float
    equity_high_water_mark: float
    current_equity: float
    current_open_risk_fraction: float
    active_theses: int
    daily_realized_pnl: float = 0.0
    daily_unrealized_pnl: float = 0.0

    @property
    def daily_loss_fraction(self) -> float:
        if self.start_of_day_equity <= 0:
            return 1.0
        pnl = self.daily_realized_pnl + self.daily_unrealized_pnl
        return max(0.0, -pnl / self.start_of_day_equity)

    @property
    def overall_drawdown_fraction(self) -> float:
        if self.equity_high_water_mark <= 0:
            return 1.0
        return max(0.0, 1.0 - self.current_equity / self.equity_high_water_mark)


@dataclass(frozen=True, slots=True)
class DataFreshness:
    market_age_seconds: float
    statistics_age_seconds: float
    fundamental_age_seconds: float
    pattern_age_seconds: float
    execution_age_seconds: float
    risk_age_seconds: float


@dataclass(frozen=True, slots=True)
class DecisionContext:
    market: MarketSnapshot
    statistics: StatisticsSnapshot
    fundamental: FundamentalSnapshot
    pattern: PatternSnapshot
    execution: ExecutionSnapshot
    risk: RiskSnapshot
    freshness: DataFreshness
    system_state: SystemState
    evaluated_at: datetime = field(default_factory=utc_now)


@dataclass(frozen=True, slots=True)
class TradeProposal:
    decision_id: str
    setup_id: str
    thesis_id: str
    strategy_mode: StrategyMode
    action: DecisionAction
    direction: TradeSide
    calibrated_probability: float
    expected_value_net: float
    requested_risk_fraction: float
    requested_lot: float
    structural_target: float
    structural_invalidation: float
    tranche_number: int = 1
    is_existing_thesis: bool = False
    reason_summary: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class RiskApproval:
    decision_id: str
    status: DecisionStatus
    approved: bool
    approved_risk_fraction: float
    projected_loss_fraction: float
    approved_lot: float
    reasons: tuple[str, ...]
    limits: dict[str, Any]
