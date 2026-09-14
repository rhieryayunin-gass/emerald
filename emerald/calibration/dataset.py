from __future__ import annotations

import hashlib
import json
import math
import sqlite3
from collections import Counter
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

FEATURES = (
    "log_displacement_points",
    "log_displacement_zscore",
    "reclaim_fraction",
    "log_spread_expansion",
    "log_reward_risk",
)
COHORT_FIELDS = (
    "broker_id",
    "symbol",
    "strategy_mode",
    "shadow_tier",
    "direction",
    "detector_version",
)
MODES = {"REGULAR_MISMATCH", "ROLLOVER_REVERSAL", "NEWS_REVERSAL"}
TIERS = {"STANDARD", "EXPLORATORY", "ROLLOVER_EXPLORATORY"}


def timestamp(value: object) -> datetime:
    result = datetime.fromisoformat(str(value))
    if result.tzinfo is None:
        raise ValueError("timestamp must include timezone")
    return result.astimezone(UTC)


def finite(value: object, *, positive: bool = False) -> float:
    result = float(value)
    if not math.isfinite(result) or (positive and result <= 0):
        raise ValueError("invalid numeric value")
    return result


def cohort(row: dict) -> tuple[str, ...]:
    values = tuple(str(row[key]).strip() for key in COHORT_FIELDS)
    broker, symbol, mode, tier, side, version = values
    if (
        not broker
        or not version
        or symbol.upper() != "XAUUSD"
        or mode not in MODES
        or tier not in TIERS
        or side not in {"BUY", "SELL"}
    ):
        raise ValueError("unsupported cohort")
    return broker.casefold(), symbol.upper(), mode, tier, side, version


def features(payload: dict, side: str) -> list[float]:
    entry = finite(payload["entry_reference"], positive=True)
    target = finite(payload["structural_target"], positive=True)
    stop = finite(payload["structural_invalidation"], positive=True)
    if side == "BUY":
        valid = stop < entry < target
    else:
        valid = side == "SELL" and target < entry < stop
    if not valid:
        raise ValueError("invalid executable price structure")
    displacement = finite(payload["displacement_points"], positive=True)
    zscore = finite(payload["displacement_zscore"], positive=True)
    reclaim = finite(payload["reclaim_fraction"])
    baseline = finite(payload["baseline_spread_points"], positive=True)
    peak = finite(payload["peak_spread_points"], positive=True)
    if not 0 <= reclaim <= 1.5:
        raise ValueError("invalid reclaim")
    return [
        math.log1p(displacement),
        math.log1p(zscore),
        reclaim,
        math.log1p(peak / baseline),
        math.log1p(abs(target - entry) / abs(stop - entry)),
    ]


def read_snapshot(path: Path) -> tuple[list[dict], str]:
    """One read transaction, without initializing/migrating or copying private account tables."""
    uri = path.resolve().as_uri() + "?mode=ro"
    with sqlite3.connect(uri, uri=True, timeout=10) as connection:
        connection.row_factory = sqlite3.Row
        connection.execute("BEGIN")
        columns = {row["name"] for row in connection.execute("PRAGMA table_info(detector_events)")}
        required = set(COHORT_FIELDS) | {
            "event_id",
            "input_hash",
            "confirmed",
            "spread_artifact",
            "payload_json",
            "label_status",
            "outcome_json",
            "created_at",
            "labelled_at",
        }
        if not required.issubset(columns):
            raise ValueError("database is missing the EMERALD v0.4 detector-event schema")
        query = "SELECT " + ",".join(sorted(required)) + " FROM detector_events ORDER BY event_id"
        rows = [dict(row) for row in connection.execute(query)]
    digest = hashlib.sha256(
        json.dumps(rows, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    return rows, digest


@dataclass(frozen=True)
class Sample:
    event_id: str
    cohort: tuple[str, ...]
    start: datetime
    end: datetime
    available_at: datetime
    x: list[float]
    y: int
    reward_points: float
    risk_points: float
    pnl_points: float


def prepare(rows: list[dict], as_of: datetime) -> tuple[list[Sample], dict, list[dict]]:
    """Deduplicate price episodes before the time split; labels never become features."""
    candidates = []
    rejected = Counter()
    incomplete = []
    seen = set()
    seen_ids = set()
    for row in rows:
        state = row.get("label_status")
        if state not in {"TARGET_HIT", "STOP_HIT"}:
            rejected[str(state or "MISSING_LABEL")] += 1
            if row.get("confirmed") and state in {"PENDING", "CENSORED"}:
                try:
                    payload = json.loads(row["payload_json"])
                    incomplete.append(
                        {"cohort": cohort(row), "start": timestamp(payload["confirmed_at"])}
                    )
                except (KeyError, ValueError, TypeError):
                    rejected["MALFORMED_INCOMPLETE_EVENT"] += 1
            continue
        try:
            key = cohort(row)
            if row["confirmed"] != 1 or row["spread_artifact"] != 0:
                raise ValueError("unconfirmed or spread artifact")
            payload = json.loads(row["payload_json"])
            outcome = json.loads(row["outcome_json"])
            if (
                payload.get("reversal_confirmed") is not True
                or payload.get("spread_artifact") is not False
            ):
                raise ValueError("inconsistent detector flags")
            if outcome["event_id"] != row["event_id"] or outcome["outcome"] != state:
                raise ValueError("inconsistent label identity")
            start = timestamp(payload["confirmed_at"])
            end = timestamp(outcome["resolved_at"])
            available = max(end, timestamp(row["labelled_at"]))
            if (
                end <= start
                or available > as_of
                or timestamp(outcome["confirmed_at"]) != start
                or timestamp(payload["extreme_time"]) > start
            ):
                raise ValueError("inconsistent/future event times")
            risk = finite(outcome["risk_points"], positive=True)
            reward = finite(outcome["reward_points"], positive=True)
            pnl = finite(outcome["pnl_points"])
            x = features(payload, key[4])
            expected_side = "BID" if key[4] == "BUY" else "ASK"
            if outcome["pricing_side"] != expected_side:
                raise ValueError("wrong execution side")
            if not math.isclose(
                finite(outcome["entry_reference"]), finite(payload["entry_reference"]), abs_tol=1e-6
            ):
                raise ValueError("entry mismatch")
            if not math.isclose(reward / risk, math.expm1(x[-1]), rel_tol=1e-4, abs_tol=1e-6):
                raise ValueError("inconsistent reward/risk")
            if (state == "TARGET_HIT" and pnl < reward - 1e-4) or (
                state == "STOP_HIT" and pnl > -risk + 1e-4
            ):
                raise ValueError("label contradicts executable PnL")
            # Historical news rows can be classified before release; those are not reversals.
            if key[2] == "NEWS_REVERSAL":
                news = payload["classification"]["news"]
                event = news["matched_event"]
                if (
                    news["source_health"] != "HEALTHY"
                    or not news["fresh"]
                    or event["currency"] != "USD"
                    or event["impact"] != "High"
                    or timestamp(event["scheduled_at"]) > timestamp(payload["extreme_time"])
                ):
                    raise ValueError("news release not verified before displacement")
            signature = (key[:2], str(row["input_hash"]))
            if not row["input_hash"] or signature in seen or row["event_id"] in seen_ids:
                rejected["DUPLICATE_INPUT"] += 1
                continue
            seen.add(signature)
            seen_ids.add(row["event_id"])
            candidates.append(
                Sample(
                    str(row["event_id"]),
                    key,
                    start,
                    end,
                    available,
                    x,
                    int(state == "TARGET_HIT"),
                    reward,
                    risk,
                    pnl,
                )
            )
        except (KeyError, ValueError, TypeError, OverflowError):
            rejected["INVALID_RESOLVED_EVENT"] += 1
    # Use the first signal in an overlapping broker/symbol episode, across tiers and sides.
    # Counts therefore represent separate opportunities, not repeated ticks of one spike.
    samples = []
    busy_until = {}
    for sample in sorted(candidates, key=lambda item: (item.start, item.event_id)):
        instrument = sample.cohort[:2]
        if instrument in busy_until and sample.start <= busy_until[instrument]:
            rejected["OVERLAPPING_EPISODE"] += 1
            continue
        busy_until[instrument] = sample.end
        samples.append(sample)
    return (
        samples,
        {
            "total_rows": len(rows),
            "usable_samples": len(samples),
            "excluded": dict(sorted(rejected.items())),
        },
        incomplete,
    )
