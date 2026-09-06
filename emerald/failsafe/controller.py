from dataclasses import dataclass
from enum import StrEnum

from emerald.domain.enums import SystemState
from emerald.risk.config import RiskConfig


class FailSafeAction(StrEnum):
    NONE = "NONE"
    BLOCK_NEW_ENTRIES = "BLOCK_NEW_ENTRIES"
    CLOSE_REGULAR_FOR_ROLLOVER = "CLOSE_REGULAR_FOR_ROLLOVER"
    EMERGENCY_CLOSE_ALL = "EMERGENCY_CLOSE_ALL"


@dataclass(frozen=True, slots=True)
class HealthSnapshot:
    ai_heartbeat_age_seconds: float
    api_heartbeat_age_seconds: float
    market_data_age_seconds: float
    mt5_connected: bool
    state_reconciled: bool
    ambiguous_orders: int = 0


@dataclass(frozen=True, slots=True)
class LocalRiskSnapshot:
    daily_loss_fraction: float
    overall_drawdown_fraction: float
    margin_level: float
    rollover_flatten_due: bool = False
    has_regular_positions: bool = False


@dataclass(frozen=True, slots=True)
class FailSafeDecision:
    system_state: SystemState
    allow_new_entries: bool
    actions: tuple[FailSafeAction, ...]
    reasons: tuple[str, ...]


class FailSafeController:
    def __init__(
        self,
        config: RiskConfig | None = None,
        heartbeat_timeout_seconds: float = 15.0,
        market_timeout_seconds: float = 3.0,
        minimum_margin_level: float = 150.0,
    ) -> None:
        self.config = config or RiskConfig()
        self.heartbeat_timeout_seconds = heartbeat_timeout_seconds
        self.market_timeout_seconds = market_timeout_seconds
        self.minimum_margin_level = minimum_margin_level

    def evaluate(self, health: HealthSnapshot, risk: LocalRiskSnapshot) -> FailSafeDecision:
        reasons: list[str] = []
        actions: list[FailSafeAction] = []

        if risk.overall_drawdown_fraction >= self.config.overall_drawdown_hard_stop:
            return FailSafeDecision(
                system_state=SystemState.HARD_STOP,
                allow_new_entries=False,
                actions=(FailSafeAction.EMERGENCY_CLOSE_ALL,),
                reasons=("OVERALL_DRAWDOWN_HARD_STOP",),
            )
        if risk.daily_loss_fraction >= self.config.daily_loss_hard_stop:
            return FailSafeDecision(
                system_state=SystemState.HARD_STOP,
                allow_new_entries=False,
                actions=(FailSafeAction.EMERGENCY_CLOSE_ALL,),
                reasons=("DAILY_LOSS_HARD_STOP",),
            )
        if risk.margin_level > 0 and risk.margin_level < self.minimum_margin_level:
            return FailSafeDecision(
                system_state=SystemState.FAIL_SAFE,
                allow_new_entries=False,
                actions=(FailSafeAction.EMERGENCY_CLOSE_ALL,),
                reasons=("MARGIN_LEVEL_CRITICAL",),
            )

        if not health.mt5_connected:
            reasons.append("MT5_DISCONNECTED")
        if health.ai_heartbeat_age_seconds > self.heartbeat_timeout_seconds:
            reasons.append("AI_HEARTBEAT_EXPIRED")
        if health.api_heartbeat_age_seconds > self.heartbeat_timeout_seconds:
            reasons.append("API_HEARTBEAT_EXPIRED")
        if health.market_data_age_seconds > self.market_timeout_seconds:
            reasons.append("MARKET_DATA_STALE")
        if not health.state_reconciled:
            reasons.append("STATE_NOT_RECONCILED")
        if health.ambiguous_orders:
            reasons.append("AMBIGUOUS_EXECUTION_EXISTS")

        if reasons:
            actions.append(FailSafeAction.BLOCK_NEW_ENTRIES)

        if risk.rollover_flatten_due and risk.has_regular_positions:
            actions.append(FailSafeAction.CLOSE_REGULAR_FOR_ROLLOVER)
            reasons.append("ROLLOVER_FLATTEN_DUE")

        if reasons:
            return FailSafeDecision(
                system_state=SystemState.FAIL_SAFE,
                allow_new_entries=False,
                actions=tuple(dict.fromkeys(actions)),
                reasons=tuple(dict.fromkeys(reasons)),
            )

        return FailSafeDecision(
            system_state=SystemState.ACTIVE,
            allow_new_entries=True,
            actions=(FailSafeAction.NONE,),
            reasons=("ALL_HEALTH_CHECKS_PASSED",),
        )
