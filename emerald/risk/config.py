from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class RiskConfig:
    minimum_probability: float = 0.80
    regular_max_risk: float = 0.10
    special_max_risk: float = 0.05
    aggregate_open_risk: float = 0.10
    daily_loss_hard_stop: float = 0.20
    overall_drawdown_hard_stop: float = 0.50
    maximum_total_lot: float = 0.50
    maximum_active_theses: int = 2
    maximum_tranches_per_thesis: int = 5
    allow_real_trading: bool = False
    market_max_age_seconds: float = 3.0
    statistics_max_age_seconds: float = 30.0
    fundamental_max_age_seconds: float = 60.0
    pattern_max_age_seconds: float = 5.0
    execution_max_age_seconds: float = 3.0
    risk_max_age_seconds: float = 3.0
