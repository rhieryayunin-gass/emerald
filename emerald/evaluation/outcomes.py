from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime

from emerald.domain import TradeSide
from emerald.market import TickQuote


@dataclass(frozen=True, slots=True)
class OutcomeResult:
    event_id: str
    outcome: str
    confirmed_at: datetime
    resolved_at: datetime
    entry_reference: float
    exit_price: float
    pnl_points: float
    risk_points: float
    reward_points: float
    r_multiple: float
    duration_seconds: float
    pricing_side: str


class ShadowOutcomeLabeller:
    """Label target-vs-stop order from executable Bid/Ask prices after confirmation."""

    def evaluate(
        self,
        *,
        event_id: str,
        direction: TradeSide,
        confirmed_at: datetime,
        entry_reference: float,
        structural_target: float,
        structural_invalidation: float,
        point: float,
        ticks: tuple[TickQuote, ...],
    ) -> OutcomeResult | None:
        numeric = (entry_reference, structural_target, structural_invalidation, point)
        if not all(math.isfinite(value) for value in numeric) or point <= 0:
            raise ValueError("outcome inputs must be finite and point must be positive")
        if confirmed_at.tzinfo is None:
            raise ValueError("confirmed_at must be timezone-aware")

        if direction is TradeSide.BUY:
            if not structural_invalidation < entry_reference < structural_target:
                raise ValueError("BUY structure must be invalidation < entry < target")
        elif not structural_target < entry_reference < structural_invalidation:
            raise ValueError("SELL structure must be target < entry < invalidation")

        risk_points = abs(entry_reference - structural_invalidation) / point
        reward_points = abs(structural_target - entry_reference) / point
        for tick in ticks:
            if tick.broker_time <= confirmed_at:
                continue
            if direction is TradeSide.BUY:
                exit_price = tick.bid
                outcome = (
                    "STOP_HIT"
                    if exit_price <= structural_invalidation
                    else "TARGET_HIT" if exit_price >= structural_target else None
                )
                pnl_points = (exit_price - entry_reference) / point
                pricing_side = "BID"
            else:
                exit_price = tick.ask
                outcome = (
                    "STOP_HIT"
                    if exit_price >= structural_invalidation
                    else "TARGET_HIT" if exit_price <= structural_target else None
                )
                pnl_points = (entry_reference - exit_price) / point
                pricing_side = "ASK"
            if outcome is None:
                continue
            return OutcomeResult(
                event_id=event_id,
                outcome=outcome,
                confirmed_at=confirmed_at,
                resolved_at=tick.broker_time,
                entry_reference=entry_reference,
                exit_price=exit_price,
                pnl_points=round(pnl_points, 6),
                risk_points=round(risk_points, 6),
                reward_points=round(reward_points, 6),
                r_multiple=round(pnl_points / risk_points, 6),
                duration_seconds=(tick.broker_time - confirmed_at).total_seconds(),
                pricing_side=pricing_side,
            )
        return None
