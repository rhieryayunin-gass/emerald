import hashlib
import hmac
import json
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path
from zoneinfo import ZoneInfo
from typing import Annotated

from fastapi import FastAPI, Header, HTTPException, Query, status
from fastapi.middleware.trustedhost import TrustedHostMiddleware

from emerald import __version__
from emerald.detectors import DetectorConfig, MismatchDetector
from emerald.domain import DecisionContext, StrategyMode, TradeProposal, TradeSide
from emerald.evaluation import ShadowOutcomeLabeller, wilson_interval
from emerald.fundamental import EconomicCalendarClient
from emerald.journal import SQLiteJournal
from emerald.market import TickQuote, TickStore
from emerald.risk import HardRiskEngine, RiskConfig
from emerald.strategies import StrategyClassifier

from .schemas import ExecutorHeartbeatPayload, TickBatchPayload
from .settings import Settings

settings = Settings()
app = FastAPI(
    title="RIRI EMERALD Brain API",
    version=__version__,
    docs_url="/docs" if settings.expose_api_docs else None,
    redoc_url="/redoc" if settings.expose_api_docs else None,
    openapi_url="/openapi.json" if settings.expose_api_docs else None,
)
app.add_middleware(TrustedHostMiddleware, allowed_hosts=settings.trusted_host_list)
config = RiskConfig(allow_real_trading=settings.allow_real_trading)
risk_engine = HardRiskEngine(config)
tick_store = TickStore()
mismatch_detector = MismatchDetector()
rollover_detector = MismatchDetector(DetectorConfig(
    minimum_ticks=7, baseline_ticks=4, confirmation_ticks=2,
    minimum_displacement_points=15.0, minimum_displacement_zscore=1.5,
    minimum_reclaim_fraction=0.25, joint_quote_move_ratio=0.35,
    maximum_spread_expansion_ratio=6.0,
))
exploratory_detector = MismatchDetector(DetectorConfig(
    minimum_ticks=7, baseline_ticks=4, confirmation_ticks=2,
    minimum_displacement_points=20.0, minimum_displacement_zscore=1.75,
    minimum_reclaim_fraction=0.30,
))
outcome_labeller = ShadowOutcomeLabeller()
journal_path = Path(settings.journal_path)
journal_path.parent.mkdir(parents=True, exist_ok=True)
journal = SQLiteJournal(journal_path)
journal.initialize()
calendar_client = EconomicCalendarClient(
    url=settings.news_calendar_url,
    refresh_seconds=settings.news_calendar_refresh_seconds,
    timeout_seconds=settings.news_calendar_timeout_seconds,
)
strategy_classifier = StrategyClassifier(
    morning_start_minute=settings.rollover_window_start_minute_wib,
    morning_end_minute=settings.rollover_window_end_minute_wib,
)


def require_api_token(authorization: str | None) -> None:
    expected = f"Bearer {settings.api_token}"
    if authorization is None or not hmac.compare_digest(authorization, expected):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="invalid API token",
        )


def label_pending_shadow_events(
    *,
    broker_id: str,
    symbol: str,
    point: float,
    ticks: tuple[TickQuote, ...],
) -> int:
    labelled = 0
    pending = journal.list_pending_detector_events(broker_id=broker_id, symbol=symbol)
    required = {
        "confirmed_at",
        "entry_reference",
        "structural_target",
        "structural_invalidation",
    }
    for event in pending:
        candidate = json.loads(event["payload_json"])
        if not required.issubset(candidate):
            if journal.label_detector_event(
                event_id=event["event_id"],
                outcome="CENSORED",
                payload={"reason": "LEGACY_EVENT_MISSING_EXECUTABLE_PRICE_FIELDS"},
            ):
                labelled += 1
            continue
        result = outcome_labeller.evaluate(
            event_id=event["event_id"],
            direction=TradeSide(event["direction"]),
            confirmed_at=datetime.fromisoformat(candidate["confirmed_at"]),
            entry_reference=float(candidate["entry_reference"]),
            structural_target=float(candidate["structural_target"]),
            structural_invalidation=float(candidate["structural_invalidation"]),
            point=point,
            ticks=ticks,
        )
        if result is not None and journal.label_detector_event(
            event_id=event["event_id"],
            outcome=result.outcome,
            payload=asdict(result),
        ):
            labelled += 1
    return labelled


@app.get("/health")
def health() -> dict[str, object]:
    return {
        "service": "riri-emerald-brain",
        "status": "ok",
        "environment": settings.environment,
        "real_trading_allowed": config.allow_real_trading,
        "probability_model_ready": settings.probability_model_ready,
        "version": __version__,
    }


@app.get("/rules")
def rules() -> dict[str, object]:
    return {
        "minimum_probability": config.minimum_probability,
        "regular_max_risk": config.regular_max_risk,
        "special_max_risk": config.special_max_risk,
        "aggregate_open_risk": config.aggregate_open_risk,
        "daily_loss_hard_stop": config.daily_loss_hard_stop,
        "overall_drawdown_hard_stop": config.overall_drawdown_hard_stop,
        "maximum_total_lot": config.maximum_total_lot,
        "maximum_active_theses": config.maximum_active_theses,
        "maximum_tranches_per_thesis": config.maximum_tranches_per_thesis,
    }


@app.post("/risk/evaluate")
def evaluate_risk(
    proposal: TradeProposal,
    context: DecisionContext,
    authorization: Annotated[str | None, Header()] = None,
) -> dict[str, object]:
    """Evaluate an entry proposal using the authoritative deterministic gates."""
    require_api_token(authorization)
    return asdict(risk_engine.evaluate(proposal, context))


@app.post("/market/ticks")
def ingest_ticks(
    payload: TickBatchPayload,
    authorization: Annotated[str | None, Header()] = None,
) -> dict[str, object]:
    """Ingest ordered Bid/Ask ticks and return the latest deterministic candidate."""
    require_api_token(authorization)
    symbols = {tick.symbol.strip().upper() for tick in payload.ticks}
    if len(symbols) != 1:
        raise HTTPException(status_code=422, detail="one batch must contain exactly one symbol")
    quotes = [
        TickQuote(
            symbol=tick.symbol,
            bid=tick.bid,
            ask=tick.ask,
            broker_time=tick.broker_time,
            observed_at=tick.observed_at,
            volume=tick.volume,
        )
        for tick in payload.ticks
    ]
    try:
        accepted = tick_store.append_many(payload.broker_id, quotes)
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error

    symbol = next(iter(symbols))
    outcomes_labelled = label_pending_shadow_events(
        broker_id=payload.broker_id,
        symbol=symbol,
        point=payload.point,
        ticks=tuple(quotes),
    )
    window = tick_store.snapshot(payload.broker_id, symbol)
    analysis_window = window[-mismatch_detector.config.minimum_ticks :]
    result = mismatch_detector.detect(analysis_window, payload.point)
    shadow_tier = "STANDARD"
    if result.candidate is not None:
        jakarta = result.candidate.extreme_time.astimezone(ZoneInfo("Asia/Jakarta"))
        minute = jakarta.hour * 60 + jakarta.minute
        if settings.rollover_window_start_minute_wib <= minute < settings.rollover_window_end_minute_wib:
            analysis_window = window[-rollover_detector.config.minimum_ticks :]
            result = rollover_detector.detect(analysis_window, payload.point)
            shadow_tier = "ROLLOVER_EXPLORATORY"
        elif settings.exploratory_shadow_enabled and not result.candidate.reversal_confirmed:
            analysis_window = window[-exploratory_detector.config.minimum_ticks :]
            result = exploratory_detector.detect(analysis_window, payload.point)
            shadow_tier = "EXPLORATORY"
    event_recorded = False
    if result.candidate is not None:
        candidate_payload = asdict(result.candidate)
        news_context = calendar_client.context_for(
            result.candidate.extreme_time,
            before_minutes=settings.news_window_before_minutes,
            after_minutes=settings.news_window_after_minutes,
        )
        strategy_mode, classification = strategy_classifier.classify(
            event_time=result.candidate.extreme_time,
            news_context=news_context,
        )
        candidate_payload["classification"] = classification
        event_key = (
            f"{payload.broker_id.casefold()}|{symbol}|"
            f"{result.candidate.direction}|{result.candidate.extreme_time.isoformat()}"
        )
        event_id = hashlib.sha256(event_key.encode()).hexdigest()
        input_json = json.dumps(
            [asdict(tick) for tick in analysis_window],
            default=str,
            sort_keys=True,
            separators=(",", ":"),
        )
        event_recorded = journal.record_detector_event(
            event_id=event_id,
            broker_id=payload.broker_id,
            symbol=symbol,
            strategy_mode=strategy_mode.value,
            shadow_tier=shadow_tier,
            direction=result.candidate.direction.value,
            confirmed=result.candidate.reversal_confirmed,
            spread_artifact=result.candidate.spread_artifact,
            detector_version="mismatch-v0.4.0",
            input_hash=hashlib.sha256(input_json.encode()).hexdigest(),
            payload=candidate_payload,
            label_status="PENDING" if result.candidate.reversal_confirmed else "FILTERED",
        )
    return {
        "accepted_ticks": accepted,
        "stored_ticks": len(window),
        "detector": asdict(result),
        "probability_status": "NOT_CALIBRATED",
        "entry_eligible": False,
        "shadow_event_recorded": event_recorded,
        "shadow_outcomes_labelled": outcomes_labelled,
    }


@app.post("/executor/heartbeat")
def executor_heartbeat(
    payload: ExecutorHeartbeatPayload,
    authorization: Annotated[str | None, Header()] = None,
) -> dict[str, object]:
    """Validate and persist demo executor health for risk gating and the dashboard."""
    require_api_token(authorization)
    configuration_conflicts: list[str] = []
    if payload.account_server != settings.expected_account_server:
        configuration_conflicts.append("ACCOUNT_SERVER_MISMATCH")
    if payload.symbol != settings.expected_symbol:
        configuration_conflicts.append("SYMBOL_MISMATCH")
    if payload.leverage != settings.expected_leverage:
        configuration_conflicts.append("LEVERAGE_MISMATCH")
    if configuration_conflicts:
        raise HTTPException(status_code=409, detail=configuration_conflicts)

    values = payload.model_dump(mode="json")
    previous_incident = journal.record_executor_status(
        account_login=payload.account_login,
        account_server=payload.account_server,
        system_state=payload.system_state,
        incident_code=payload.incident,
        payload=values,
    )
    if previous_incident and previous_incident != "NONE" and previous_incident != payload.incident:
        previous_id = hashlib.sha256(
            f"executor|{payload.account_login}|{previous_incident}".encode()
        ).hexdigest()
        journal.resolve_incident(previous_id)
    if payload.incident != "NONE":
        incident_id = hashlib.sha256(
            f"executor|{payload.account_login}|{payload.incident}".encode()
        ).hexdigest()
        journal.upsert_incident(
            incident_id=incident_id,
            severity="CRITICAL" if payload.system_state == "HARD_STOP" else "HIGH",
            component="MT5_EXECUTOR",
            code=payload.incident,
            details=values,
        )
    healthy = (
        payload.system_state == "ACTIVE"
        and payload.incident == "NONE"
        and payload.terminal_connected
        and payload.account_trade_allowed
        and payload.expert_trade_allowed
    )
    return {
        "accepted": True,
        "account_login": payload.account_login,
        "system_state": payload.system_state,
        "executor_healthy": healthy,
        "new_entries_allowed": (
            healthy
            and settings.environment == "demo"
            and settings.probability_model_ready
        ),
    }


@app.get("/executor/status")
def executor_status(
    authorization: Annotated[str | None, Header()] = None,
) -> dict[str, object]:
    require_api_token(authorization)
    rows = journal.list_executor_statuses()
    for row in rows:
        row["payload"] = json.loads(row.pop("payload_json"))
    return {"executors": rows, "count": len(rows)}


@app.get("/telemetry/readiness")
def telemetry_readiness(
    authorization: Annotated[str | None, Header()] = None,
) -> dict[str, object]:
    """Explain exactly which telemetry and entry gates are currently blocking."""
    require_api_token(authorization)
    now = datetime.now(UTC)
    executor_rows = journal.list_executor_statuses()
    executor_details: list[dict[str, object]] = []
    executor_healthy = False
    for row in executor_rows:
        received_at = datetime.fromisoformat(str(row["received_at"]))
        age_seconds = max(0.0, (now - received_at).total_seconds())
        payload = json.loads(row["payload_json"])
        healthy = (
            age_seconds <= settings.executor_heartbeat_max_age_seconds
            and row["system_state"] == "ACTIVE"
            and row["incident_code"] == "NONE"
            and payload["terminal_connected"]
            and payload["account_trade_allowed"]
            and payload["expert_trade_allowed"]
        )
        executor_healthy = executor_healthy or healthy
        executor_details.append(
            {
                "account_login": row["account_login"],
                "account_server": row["account_server"],
                "system_state": row["system_state"],
                "incident": row["incident_code"],
                "heartbeat_age_seconds": round(age_seconds, 3),
                "healthy": healthy,
            }
        )

    stream_details: list[dict[str, object]] = []
    stream_healthy = False
    for stream in tick_store.stream_statuses():
        observed_at = stream["latest_observed_at"]
        if not isinstance(observed_at, datetime):
            continue
        age_seconds = max(0.0, (now - observed_at.astimezone(UTC)).total_seconds())
        healthy = (
            str(stream["symbol"]).upper() == settings.expected_symbol
            and age_seconds <= settings.tick_stream_max_age_seconds
        )
        stream_healthy = stream_healthy or healthy
        stream_details.append(
            {
                **stream,
                "latest_broker_time": str(stream["latest_broker_time"]),
                "latest_observed_at": str(observed_at),
                "tick_age_seconds": round(age_seconds, 3),
                "healthy": healthy,
            }
        )

    blockers: list[str] = []
    if not executor_rows:
        blockers.append("EXECUTOR_NOT_SEEN")
    elif not executor_healthy:
        blockers.append("EXECUTOR_NOT_HEALTHY")
    if not stream_details:
        blockers.append("TICK_STREAM_NOT_SEEN")
    elif not stream_healthy:
        blockers.append("TICK_STREAM_NOT_HEALTHY")
    telemetry_ready = executor_healthy and stream_healthy
    if not settings.probability_model_ready:
        blockers.append("PROBABILITY_MODEL_NOT_READY")

    return {
        "telemetry_ready": telemetry_ready,
        "entry_ready": telemetry_ready and settings.probability_model_ready,
        "blockers": blockers,
        "expected_profile": {
            "server": settings.expected_account_server,
            "symbol": settings.expected_symbol,
            "leverage": settings.expected_leverage,
            "timezone": "GMT+7",
        },
        "executors": executor_details,
        "tick_streams": stream_details,
    }


@app.get("/shadow/events")
def shadow_events(
    authorization: Annotated[str | None, Header()] = None,
    limit: Annotated[int, Query(ge=1, le=1000)] = 100,
) -> dict[str, object]:
    """Expose detector events for the future dashboard and calibration workflow."""
    require_api_token(authorization)
    events = journal.list_detector_events(limit)
    for event in events:
        event["payload"] = json.loads(event.pop("payload_json"))
        outcome_json = event.pop("outcome_json")
        event["outcome"] = json.loads(outcome_json) if outcome_json else None
    return {"events": events, "count": len(events)}


@app.get("/shadow/metrics")
def shadow_metrics(
    authorization: Annotated[str | None, Header()] = None,
) -> dict[str, object]:
    """Expose dataset maturity; these values are not calibrated trade probabilities."""
    require_api_token(authorization)
    rows_by_mode = {
        str(row["strategy_mode"]): row for row in journal.detector_metrics_by_mode()
    }
    required_modes = [mode.value for mode in StrategyMode]
    modes: list[dict[str, object]] = []
    all_sample_gates_met = True
    for mode in required_modes:
        row = rows_by_mode.get(mode, {})
        target_hits = int(row.get("target_hits") or 0)
        stop_hits = int(row.get("stop_hits") or 0)
        resolved = target_hits + stop_hits
        interval_low, interval_high = wilson_interval(target_hits, resolved)
        minimum_samples = (
            settings.minimum_calibration_samples_per_mode
            if mode == StrategyMode.REGULAR_MISMATCH.value
            else settings.special_minimum_calibration_samples
        )
        sample_gate_met = resolved >= minimum_samples
        all_sample_gates_met = all_sample_gates_met and sample_gate_met
        modes.append(
            {
                "strategy_mode": mode,
                "total_events": int(row.get("total_events") or 0),
                "confirmed_events": int(row.get("confirmed_events") or 0),
                "pending_events": int(row.get("pending_events") or 0),
                "target_hits": target_hits,
                "stop_hits": stop_hits,
                "censored_events": int(row.get("censored_events") or 0),
                "filtered_events": int(row.get("filtered_events") or 0),
                "resolved_outcomes": resolved,
                "observed_target_rate": round(target_hits / resolved, 6) if resolved else None,
                "wilson_95_interval": [interval_low, interval_high],
                "minimum_samples": minimum_samples,
                "sample_gate_met": sample_gate_met,
            }
        )
    return {
        "modes": modes,
        "all_sample_gates_met": all_sample_gates_met,
        "probability_model_ready": settings.probability_model_ready,
        "calibration_ready": all_sample_gates_met and settings.probability_model_ready,
        "notice": "Observed outcomes and confidence intervals are not calibrated probabilities.",
    }


@app.get("/incidents")
def incidents(
    authorization: Annotated[str | None, Header()] = None,
) -> dict[str, object]:
    """Expose unresolved incidents for the future web frontend."""
    require_api_token(authorization)
    rows = journal.list_open_incidents()
    for row in rows:
        row["details"] = json.loads(row.pop("details_json"))
    return {"incidents": rows, "count": len(rows)}
