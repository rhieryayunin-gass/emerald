from __future__ import annotations

import math
from decimal import ROUND_DOWN, Decimal

from emerald.domain.enums import (
    AccountTradeMode,
    DecisionAction,
    DecisionStatus,
    StrategyMode,
    SystemState,
)
from emerald.domain.models import DecisionContext, RiskApproval, TradeProposal

from .config import RiskConfig


def tier_lot_ceiling(equity: float) -> float:
    """Return the locked RIRI equity-tier lot ceiling, capped at 0.50."""
    if equity < 0:
        raise ValueError("equity cannot be negative")
    tier = math.floor(equity / 500.0) + 1
    return min(0.50, round(tier * 0.01, 2))


def floor_to_step(value: float, step: float) -> float:
    if step <= 0:
        raise ValueError("lot step must be positive")
    decimal_value = Decimal(str(max(0.0, value)))
    decimal_step = Decimal(str(step))
    units = (decimal_value / decimal_step).to_integral_value(rounding=ROUND_DOWN)
    return float(units * decimal_step)


class HardRiskEngine:
    """Authoritative deterministic gate. It may reduce or reject, never enlarge."""

    def __init__(self, config: RiskConfig | None = None) -> None:
        self.config = config or RiskConfig()

    def evaluate(self, proposal: TradeProposal, context: DecisionContext) -> RiskApproval:
        rejected: list[str] = []
        notes: list[str] = []

        self._validate_finite_numbers(proposal, context, rejected)
        self._validate_system(context, rejected)
        self._validate_freshness(context, rejected)
        self._validate_market_and_execution(context, rejected)
        self._validate_model_edge(proposal, context, rejected)
        self._validate_structure(proposal, context, rejected)
        self._validate_capacity(proposal, context, rejected)

        limits = self._limits(context, proposal)
        if rejected:
            return RiskApproval(
                decision_id=proposal.decision_id,
                status=DecisionStatus.REJECTED,
                approved=False,
                approved_risk_fraction=0.0,
                projected_loss_fraction=0.0,
                approved_lot=0.0,
                reasons=tuple(dict.fromkeys(rejected)),
                limits=limits,
            )

        setup_cap = self._setup_risk_cap(proposal.strategy_mode)
        remaining_open_risk = max(
            0.0,
            self.config.aggregate_open_risk - context.risk.current_open_risk_fraction,
        )
        remaining_daily_loss = max(
            0.0,
            self.config.daily_loss_hard_stop - context.risk.daily_loss_fraction,
        )
        remaining_drawdown = max(
            0.0,
            self.config.overall_drawdown_hard_stop - context.risk.overall_drawdown_fraction,
        )
        approved_risk = min(
            proposal.requested_risk_fraction,
            setup_cap,
            remaining_open_risk,
            remaining_daily_loss,
            remaining_drawdown,
        )

        execution = context.execution
        tier_cap = tier_lot_ceiling(execution.equity)
        loss_per_lot = self._loss_per_lot(proposal, context)
        risk_lot_ceiling = (
            approved_risk * execution.equity / loss_per_lot if loss_per_lot > 0 else 0.0
        )
        remaining_total_lot = max(0.0, self.config.maximum_total_lot - execution.current_total_lot)
        approved_lot = floor_to_step(
            min(
                proposal.requested_lot,
                risk_lot_ceiling,
                tier_cap,
                remaining_total_lot,
                execution.broker_max_lot,
                self.config.maximum_total_lot,
            ),
            execution.broker_lot_step,
        )

        if approved_risk <= 0:
            rejected.append("NO_RISK_CAPACITY")
        if approved_lot < execution.broker_min_lot:
            rejected.append("LOT_BELOW_BROKER_MINIMUM")

        projected_loss_fraction = (
            approved_lot * loss_per_lot / execution.equity if execution.equity > 0 else 1.0
        )

        if rejected:
            return RiskApproval(
                decision_id=proposal.decision_id,
                status=DecisionStatus.REJECTED,
                approved=False,
                approved_risk_fraction=0.0,
                projected_loss_fraction=0.0,
                approved_lot=0.0,
                reasons=tuple(dict.fromkeys(rejected)),
                limits=limits,
            )

        if approved_risk < proposal.requested_risk_fraction:
            notes.append("RISK_REDUCED_TO_HARD_CAP")
        if approved_lot < proposal.requested_lot:
            notes.append("LOT_REDUCED_TO_HARD_CAP")

        reduced = bool(notes)
        return RiskApproval(
            decision_id=proposal.decision_id,
            status=DecisionStatus.REDUCED if reduced else DecisionStatus.APPROVED,
            approved=True,
            approved_risk_fraction=approved_risk,
            projected_loss_fraction=projected_loss_fraction,
            approved_lot=approved_lot,
            reasons=tuple(notes or ["ALL_HARD_GATES_PASSED"]),
            limits=limits,
        )

    @staticmethod
    def _validate_finite_numbers(
        proposal: TradeProposal,
        context: DecisionContext,
        rejected: list[str],
    ) -> None:
        values = (
            proposal.calibrated_probability,
            proposal.expected_value_net,
            proposal.requested_risk_fraction,
            proposal.requested_lot,
            proposal.structural_target,
            proposal.structural_invalidation,
            context.market.bid,
            context.market.ask,
            context.market.point,
            context.execution.equity,
            context.execution.free_margin,
            context.execution.current_total_lot,
            context.execution.tick_size,
            context.execution.tick_value_loss_per_lot,
            context.risk.start_of_day_equity,
            context.risk.equity_high_water_mark,
            context.risk.current_equity,
            context.risk.current_open_risk_fraction,
        )
        if not all(math.isfinite(value) for value in values):
            rejected.append("NON_FINITE_NUMERIC_INPUT")

    def _validate_system(self, context: DecisionContext, rejected: list[str]) -> None:
        if context.system_state not in {
            SystemState.ACTIVE,
            SystemState.COLD_START,
            SystemState.THROTTLED,
        }:
            rejected.append(f"SYSTEM_STATE_{context.system_state}_BLOCKS_ENTRY")

    def _validate_freshness(self, context: DecisionContext, rejected: list[str]) -> None:
        f = context.freshness
        limits = self.config
        checks = (
            (f.market_age_seconds, limits.market_max_age_seconds, "MARKET_DATA_STALE"),
            (
                f.statistics_age_seconds,
                limits.statistics_max_age_seconds,
                "STATISTICS_DATA_STALE",
            ),
            (
                f.fundamental_age_seconds,
                limits.fundamental_max_age_seconds,
                "FUNDAMENTAL_DATA_STALE",
            ),
            (f.pattern_age_seconds, limits.pattern_max_age_seconds, "PATTERN_DATA_STALE"),
            (
                f.execution_age_seconds,
                limits.execution_max_age_seconds,
                "EXECUTION_DATA_STALE",
            ),
            (f.risk_age_seconds, limits.risk_max_age_seconds, "RISK_DATA_STALE"),
        )
        for age, maximum, reason in checks:
            if age < 0 or age > maximum:
                rejected.append(reason)

    def _validate_market_and_execution(self, context: DecisionContext, rejected: list[str]) -> None:
        market = context.market
        execution = context.execution
        if market.symbol.upper() != "XAUUSD":
            rejected.append("SYMBOL_NOT_XAUUSD")
        if not market.tradeable:
            rejected.append("MARKET_NOT_TRADEABLE")
        if not execution.terminal_connected:
            rejected.append("MT5_DISCONNECTED")
        if not execution.trade_allowed:
            rejected.append("MT5_TRADING_DISABLED")
        if (
            execution.account_trade_mode is AccountTradeMode.REAL
            and not self.config.allow_real_trading
        ):
            rejected.append("REAL_ACCOUNT_NOT_AUTHORIZED")
        if execution.account_trade_mode not in {
            AccountTradeMode.DEMO,
            AccountTradeMode.REAL,
        }:
            rejected.append("UNSUPPORTED_ACCOUNT_TRADE_MODE")
        if execution.equity <= 0 or execution.free_margin <= 0:
            rejected.append("INSUFFICIENT_ACCOUNT_CAPACITY")

    def _validate_model_edge(
        self,
        proposal: TradeProposal,
        context: DecisionContext,
        rejected: list[str],
    ) -> None:
        if proposal.action not in {
            DecisionAction.ENTER_BUY,
            DecisionAction.ENTER_SELL,
            DecisionAction.SCALE_IN,
        }:
            rejected.append("ACTION_IS_NOT_ENTRY")
        if proposal.action is DecisionAction.ENTER_BUY and proposal.direction.value != "BUY":
            rejected.append("ENTRY_ACTION_DIRECTION_CONFLICT")
        if proposal.action is DecisionAction.ENTER_SELL and proposal.direction.value != "SELL":
            rejected.append("ENTRY_ACTION_DIRECTION_CONFLICT")
        if proposal.calibrated_probability < self.config.minimum_probability:
            rejected.append("PROBABILITY_BELOW_80_PERCENT")
        if proposal.expected_value_net <= 0:
            rejected.append("EXPECTED_VALUE_NOT_POSITIVE")
        if not context.pattern.reversal_confirmed:
            rejected.append("REVERSAL_NOT_CONFIRMED")
        if proposal.direction is not context.pattern.direction:
            rejected.append("DIRECTION_CONFLICTS_WITH_PATTERN")
        if proposal.requested_risk_fraction <= 0:
            rejected.append("REQUESTED_RISK_NOT_POSITIVE")
        if proposal.requested_lot <= 0:
            rejected.append("REQUESTED_LOT_NOT_POSITIVE")

    def _validate_structure(
        self,
        proposal: TradeProposal,
        context: DecisionContext,
        rejected: list[str],
    ) -> None:
        market_mid = (context.market.bid + context.market.ask) / 2.0
        if proposal.structural_target == proposal.structural_invalidation:
            rejected.append("TARGET_EQUALS_INVALIDATION")
        if proposal.structural_target != context.pattern.structural_target:
            rejected.append("TARGET_CONFLICTS_WITH_PATTERN")
        if proposal.structural_invalidation != context.pattern.structural_invalidation:
            rejected.append("INVALIDATION_CONFLICTS_WITH_PATTERN")
        if proposal.direction.value == "BUY":
            if proposal.structural_target <= market_mid:
                rejected.append("BUY_TARGET_NOT_ABOVE_MARKET")
            if proposal.structural_invalidation >= market_mid:
                rejected.append("BUY_INVALIDATION_NOT_BELOW_MARKET")
        else:
            if proposal.structural_target >= market_mid:
                rejected.append("SELL_TARGET_NOT_BELOW_MARKET")
            if proposal.structural_invalidation <= market_mid:
                rejected.append("SELL_INVALIDATION_NOT_ABOVE_MARKET")

    def _validate_capacity(
        self,
        proposal: TradeProposal,
        context: DecisionContext,
        rejected: list[str],
    ) -> None:
        risk = context.risk
        execution = context.execution
        if risk.daily_loss_fraction >= self.config.daily_loss_hard_stop:
            rejected.append("DAILY_LOSS_HARD_STOP")
        if risk.overall_drawdown_fraction >= self.config.overall_drawdown_hard_stop:
            rejected.append("OVERALL_DRAWDOWN_HARD_STOP")
        if risk.current_open_risk_fraction >= self.config.aggregate_open_risk:
            rejected.append("AGGREGATE_OPEN_RISK_EXHAUSTED")
        if (
            not proposal.is_existing_thesis
            and risk.active_theses >= self.config.maximum_active_theses
        ):
            rejected.append("MAXIMUM_ACTIVE_THESES_REACHED")
        if proposal.tranche_number < 1 or (
            proposal.tranche_number > self.config.maximum_tranches_per_thesis
        ):
            rejected.append("INVALID_TRANCHE_NUMBER")
        if execution.current_total_lot >= self.config.maximum_total_lot:
            rejected.append("MAXIMUM_TOTAL_LOT_REACHED")
        if execution.tick_size <= 0 or execution.tick_value_loss_per_lot <= 0:
            rejected.append("INVALID_TICK_VALUE_CONTRACT")
        if proposal.tranche_number > 1 and not proposal.is_existing_thesis:
            rejected.append("SCALE_IN_REQUIRES_EXISTING_THESIS")

    def _setup_risk_cap(self, mode: StrategyMode) -> float:
        if mode is StrategyMode.REGULAR_MISMATCH:
            return self.config.regular_max_risk
        return self.config.special_max_risk

    def _loss_per_lot(self, proposal: TradeProposal, context: DecisionContext) -> float:
        execution = context.execution
        entry_price = (
            context.market.ask if proposal.direction.value == "BUY" else context.market.bid
        )
        stop_distance = abs(entry_price - proposal.structural_invalidation)
        if execution.tick_size <= 0 or execution.tick_value_loss_per_lot <= 0:
            return 0.0
        return stop_distance / execution.tick_size * execution.tick_value_loss_per_lot

    def _limits(self, context: DecisionContext, proposal: TradeProposal) -> dict[str, float | int]:
        return {
            "minimum_probability": self.config.minimum_probability,
            "setup_risk_cap": self._setup_risk_cap(proposal.strategy_mode),
            "aggregate_open_risk_cap": self.config.aggregate_open_risk,
            "daily_loss_hard_stop": self.config.daily_loss_hard_stop,
            "overall_drawdown_hard_stop": self.config.overall_drawdown_hard_stop,
            "tier_lot_ceiling": tier_lot_ceiling(context.execution.equity),
            "risk_lot_ceiling": self._risk_lot_limit_for_reporting(context, proposal),
            "maximum_total_lot": self.config.maximum_total_lot,
            "maximum_active_theses": self.config.maximum_active_theses,
            "maximum_tranches_per_thesis": self.config.maximum_tranches_per_thesis,
        }

    def _risk_lot_limit_for_reporting(
        self, context: DecisionContext, proposal: TradeProposal
    ) -> float:
        loss_per_lot = self._loss_per_lot(proposal, context)
        if loss_per_lot <= 0:
            return 0.0
        available_risk = min(
            proposal.requested_risk_fraction,
            self._setup_risk_cap(proposal.strategy_mode),
            max(0.0, self.config.aggregate_open_risk - context.risk.current_open_risk_fraction),
            max(0.0, self.config.daily_loss_hard_stop - context.risk.daily_loss_fraction),
            max(
                0.0,
                self.config.overall_drawdown_hard_stop - context.risk.overall_drawdown_fraction,
            ),
        )
        return available_risk * context.execution.equity / loss_per_lot
