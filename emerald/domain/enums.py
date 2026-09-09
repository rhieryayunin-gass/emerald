from enum import StrEnum


class StrategyMode(StrEnum):
    REGULAR_MISMATCH = "REGULAR_MISMATCH"
    ROLLOVER_REVERSAL = "ROLLOVER_REVERSAL"
    NEWS_REVERSAL = "NEWS_REVERSAL"


class SystemState(StrEnum):
    ACTIVE = "ACTIVE"
    COLD_START = "COLD_START"
    THROTTLED = "THROTTLED"
    DEGRADED = "DEGRADED"
    FAIL_SAFE = "FAIL_SAFE"
    HARD_STOP = "HARD_STOP"


class TradeSide(StrEnum):
    BUY = "BUY"
    SELL = "SELL"


class DecisionAction(StrEnum):
    ENTER_BUY = "ENTER_BUY"
    ENTER_SELL = "ENTER_SELL"
    SCALE_IN = "SCALE_IN"
    PARTIAL_CLOSE = "PARTIAL_CLOSE"
    FULL_CLOSE = "FULL_CLOSE"
    TIGHTEN_STOP = "TIGHTEN_STOP"
    TRAIL = "TRAIL"
    HOLD = "HOLD"
    NONE = "NONE"


class DecisionStatus(StrEnum):
    APPROVED = "APPROVED"
    REDUCED = "REDUCED"
    REJECTED = "REJECTED"


class AccountTradeMode(StrEnum):
    DEMO = "DEMO"
    REAL = "REAL"
    CONTEST = "CONTEST"
    UNKNOWN = "UNKNOWN"
