from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime
from itertools import pairwise
from statistics import median

from emerald.domain import TradeSide
from emerald.market import TickQuote


@dataclass(frozen=True, slots=True)
class DetectorConfig:
    minimum_ticks: int = 9
    baseline_ticks: int = 6
    confirmation_ticks: int = 2
    minimum_displacement_points: float = 30.0
    minimum_displacement_zscore: float = 2.5
    minimum_reclaim_fraction: float = 0.40
    joint_quote_move_ratio: float = 0.45
    maximum_spread_expansion_ratio: float = 4.0
    invalidation_buffer_points: float = 20.0


@dataclass(frozen=True, slots=True)
class MismatchCandidate:
    direction: TradeSide
    extreme_time: datetime
    confirmed_at: datetime
    entry_reference: float
    displacement_origin: float
    extreme_price: float
    structural_target: float
    structural_invalidation: float
    displacement_points: float
    displacement_zscore: float
    reclaim_fraction: float
    baseline_spread_points: float
    peak_spread_points: float
    spread_artifact: bool
    reversal_confirmed: bool
    detector_score: float
    evidence: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class DetectorResult:
    candidate: MismatchCandidate | None
    reasons: tuple[str, ...]
    sample_size: int


class MismatchDetector:
    """Detect displacement-and-reclaim candidates without claiming ML probability."""

    def __init__(self, config: DetectorConfig | None = None) -> None:
        self.config = config or DetectorConfig()
        if self.config.baseline_ticks < 3:
            raise ValueError("baseline_ticks must be at least 3")
        required = (
            self.config.baseline_ticks + self.config.confirmation_ticks + 1
        )
        if self.config.minimum_ticks < required:
            raise ValueError("minimum_ticks cannot be smaller than the analysis windows")

    def detect(self, ticks: tuple[TickQuote, ...], point: float) -> DetectorResult:
        if not math.isfinite(point) or point <= 0:
            raise ValueError("point must be finite and positive")
        if len(ticks) < self.config.minimum_ticks:
            return DetectorResult(None, ("INSUFFICIENT_TICKS",), len(ticks))
        if len({tick.symbol.upper() for tick in ticks}) != 1:
            raise ValueError("all ticks must use the same symbol")

        baseline = ticks[: self.config.baseline_ticks]
        search = ticks[self.config.baseline_ticks : -self.config.confirmation_ticks]
        confirmation = ticks[-self.config.confirmation_ticks :]
        if not search:
            return DetectorResult(None, ("NO_DISPLACEMENT_WINDOW",), len(ticks))

        origin_mid = median(tick.mid for tick in baseline)
        origin_bid = median(tick.bid for tick in baseline)
        origin_ask = median(tick.ask for tick in baseline)
        baseline_spread = max(point, median(tick.ask - tick.bid for tick in baseline))
        baseline_spread_points = baseline_spread / point

        low_tick = min(search, key=lambda tick: tick.mid)
        high_tick = max(search, key=lambda tick: tick.mid)
        downside = max(0.0, origin_mid - low_tick.mid)
        upside = max(0.0, high_tick.mid - origin_mid)
        direction = TradeSide.BUY if downside >= upside else TradeSide.SELL
        extreme_tick = low_tick if direction is TradeSide.BUY else high_tick
        displacement = max(downside, upside)
        displacement_points = displacement / point

        noise = self._baseline_noise(baseline, point)
        zscore = displacement / noise
        final_mid = median(tick.mid for tick in confirmation)
        if displacement <= 0:
            reclaim_fraction = 0.0
        elif direction is TradeSide.BUY:
            reclaim_fraction = (final_mid - extreme_tick.mid) / displacement
        else:
            reclaim_fraction = (extreme_tick.mid - final_mid) / displacement
        reclaim_fraction = max(0.0, min(1.5, reclaim_fraction))

        peak_spread = max(tick.ask - tick.bid for tick in search)
        peak_spread_points = peak_spread / point
        joint_ratio = self._joint_quote_move_ratio(
            direction, origin_bid, origin_ask, extreme_tick
        )
        spread_expansion = peak_spread / baseline_spread
        spread_artifact = (
            joint_ratio < self.config.joint_quote_move_ratio
            or spread_expansion > self.config.maximum_spread_expansion_ratio
        )

        evidence: list[str] = []
        reasons: list[str] = []
        if displacement_points >= self.config.minimum_displacement_points:
            evidence.append("ABNORMAL_DISPLACEMENT")
        else:
            reasons.append("DISPLACEMENT_TOO_SMALL")
        if zscore >= self.config.minimum_displacement_zscore:
            evidence.append("DISPLACEMENT_ZSCORE")
        else:
            reasons.append("DISPLACEMENT_ZSCORE_TOO_LOW")
        if reclaim_fraction >= self.config.minimum_reclaim_fraction:
            evidence.append("PRICE_RECLAIM")
        else:
            reasons.append("REVERSAL_NOT_CONFIRMED")
        if spread_artifact:
            reasons.append("SPREAD_ONLY_ARTIFACT")
        else:
            evidence.append("BID_ASK_MOVE_CONFIRMED")

        confirmation_tick = confirmation[-1]
        entry_reference = (
            confirmation_tick.ask
            if direction is TradeSide.BUY
            else confirmation_tick.bid
        )
        target_still_available = (
            entry_reference < origin_mid
            if direction is TradeSide.BUY
            else entry_reference > origin_mid
        )
        if target_still_available:
            evidence.append("STRUCTURAL_TARGET_AVAILABLE")
        else:
            reasons.append("STRUCTURAL_TARGET_ALREADY_RECLAIMED")

        reversal_confirmed = not reasons
        score = self._diagnostic_score(
            displacement_points, zscore, reclaim_fraction, spread_artifact
        )
        invalidation_buffer = self.config.invalidation_buffer_points * point
        invalidation = (
            extreme_tick.bid - invalidation_buffer
            if direction is TradeSide.BUY
            else extreme_tick.ask + invalidation_buffer
        )
        candidate = MismatchCandidate(
            direction=direction,
            extreme_time=extreme_tick.broker_time,
            confirmed_at=confirmation_tick.broker_time,
            entry_reference=entry_reference,
            displacement_origin=origin_mid,
            extreme_price=extreme_tick.mid,
            structural_target=origin_mid,
            structural_invalidation=invalidation,
            displacement_points=displacement_points,
            displacement_zscore=zscore,
            reclaim_fraction=reclaim_fraction,
            baseline_spread_points=baseline_spread_points,
            peak_spread_points=peak_spread_points,
            spread_artifact=spread_artifact,
            reversal_confirmed=reversal_confirmed,
            detector_score=score,
            evidence=tuple(evidence),
        )
        return DetectorResult(candidate, tuple(reasons or ["CANDIDATE_CONFIRMED"]), len(ticks))

    @staticmethod
    def _baseline_noise(ticks: tuple[TickQuote, ...], point: float) -> float:
        mids = [tick.mid for tick in ticks]
        changes = [abs(current - previous) for previous, current in pairwise(mids)]
        return max(point, median(changes) if changes else point)

    @staticmethod
    def _joint_quote_move_ratio(
        direction: TradeSide,
        origin_bid: float,
        origin_ask: float,
        extreme: TickQuote,
    ) -> float:
        if direction is TradeSide.BUY:
            bid_move = max(0.0, origin_bid - extreme.bid)
            ask_move = max(0.0, origin_ask - extreme.ask)
        else:
            bid_move = max(0.0, extreme.bid - origin_bid)
            ask_move = max(0.0, extreme.ask - origin_ask)
        largest = max(bid_move, ask_move)
        return min(bid_move, ask_move) / largest if largest > 0 else 0.0

    def _diagnostic_score(
        self,
        displacement_points: float,
        zscore: float,
        reclaim_fraction: float,
        spread_artifact: bool,
    ) -> float:
        displacement_component = min(
            1.0, displacement_points / self.config.minimum_displacement_points
        )
        zscore_component = min(1.0, zscore / self.config.minimum_displacement_zscore)
        reclaim_component = min(1.0, reclaim_fraction / self.config.minimum_reclaim_fraction)
        score = (displacement_component + zscore_component + reclaim_component) / 3.0
        if spread_artifact:
            score *= 0.25
        return round(score, 4)
