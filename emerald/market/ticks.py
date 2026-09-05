from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True, slots=True)
class TickQuote:
    """One broker quote. Bid and Ask are deliberately retained independently."""

    symbol: str
    bid: float
    ask: float
    broker_time: datetime
    observed_at: datetime
    volume: float = 0.0

    def __post_init__(self) -> None:
        if not self.symbol.strip():
            raise ValueError("symbol cannot be empty")
        for name in ("bid", "ask", "volume"):
            if not math.isfinite(getattr(self, name)):
                raise ValueError(f"{name} must be finite")
        if self.bid <= 0 or self.ask <= 0:
            raise ValueError("bid and ask must be positive")
        if self.ask < self.bid:
            raise ValueError("ask must be greater than or equal to bid")
        if self.volume < 0:
            raise ValueError("volume cannot be negative")
        if self.broker_time.tzinfo is None or self.observed_at.tzinfo is None:
            raise ValueError("tick timestamps must be timezone-aware")

    @property
    def mid(self) -> float:
        return (self.bid + self.ask) / 2.0

    def spread_points(self, point: float) -> float:
        if not math.isfinite(point) or point <= 0:
            raise ValueError("point must be finite and positive")
        return (self.ask - self.bid) / point
