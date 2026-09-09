from datetime import UTC, datetime

from fastapi.testclient import TestClient

from apps.brain_api.main import app, calendar_client, journal, settings, tick_store

client = TestClient(app)


def auth_headers() -> dict[str, str]:
    return {"Authorization": f"Bearer {settings.api_token}"}


def heartbeat_payload(**overrides: object) -> dict[str, object]:
    values: dict[str, object] = {
        "account_login": 123456,
        "account_server": "MetaQuotes-Demo",
        "account_company": "MetaQuotes Ltd.",
        "account_currency": "USD",
        "account_trade_mode": "DEMO",
        "margin_mode": "RETAIL_HEDGING",
        "leverage": 200,
        "symbol": "XAUUSD",
        "digits": 2,
        "point": 0.01,
        "tick_size": 0.01,
        "tick_value_loss": 1.0,
        "volume_min": 0.01,
        "volume_max": 100.0,
        "volume_step": 0.01,
        "bid": 2500.0,
        "ask": 2500.2,
        "balance": 3000.0,
        "equity": 3000.0,
        "free_margin": 3000.0,
        "margin_level": 0.0,
        "managed_positions": 0,
        "managed_lots": 0.0,
        "daily_loss_pct": 0.0,
        "high_water_drawdown_pct": 0.0,
        "seconds_until_session_close": 3600,
        "system_state": "ACTIVE",
        "incident": "NONE",
        "terminal_connected": True,
        "account_trade_allowed": True,
        "expert_trade_allowed": True,
        "server_time_epoch": 1788300000,
        "jakarta_time_epoch": 1788325200,
    }
    values.update(overrides)
    return values


def test_health_exposes_demo_lock() -> None:
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json()["environment"] == "demo"
    assert response.json()["real_trading_allowed"] is False
    assert response.json()["probability_model_ready"] is False


def test_rules_match_locked_appetite() -> None:
    rules = client.get("/rules").json()
    assert rules["minimum_probability"] == 0.8
    assert rules["regular_max_risk"] == 0.1
    assert rules["special_max_risk"] == 0.05
    assert rules["daily_loss_hard_stop"] == 0.2
    assert rules["overall_drawdown_hard_stop"] == 0.5
    assert rules["maximum_total_lot"] == 0.5


def test_heartbeat_rejects_missing_token() -> None:
    response = client.post(
        "/executor/heartbeat",
        json=heartbeat_payload(),
    )
    assert response.status_code == 401


def test_heartbeat_accepts_valid_token() -> None:
    response = client.post(
        "/executor/heartbeat",
        headers=auth_headers(),
        json=heartbeat_payload(),
    )
    assert response.status_code == 200
    assert response.json()["accepted"] is True
    assert response.json()["executor_healthy"] is True
    assert response.json()["new_entries_allowed"] is False


def test_heartbeat_rejects_wrong_account_profile() -> None:
    response = client.post(
        "/executor/heartbeat",
        headers=auth_headers(),
        json=heartbeat_payload(leverage=100),
    )
    assert response.status_code == 409
    assert "LEVERAGE_MISMATCH" in response.json()["detail"]


def test_executor_incident_is_visible_and_resolves_after_recovery() -> None:
    account_login = 888001
    failed = client.post(
        "/executor/heartbeat",
        headers=auth_headers(),
        json=heartbeat_payload(
            account_login=account_login,
            system_state="FAIL_SAFE",
            incident="API_HEARTBEAT_EXPIRED",
        ),
    )
    assert failed.status_code == 200
    assert failed.json()["new_entries_allowed"] is False
    incidents = client.get("/incidents", headers=auth_headers()).json()["incidents"]
    assert any(item["code"] == "API_HEARTBEAT_EXPIRED" for item in incidents)

    recovered = client.post(
        "/executor/heartbeat",
        headers=auth_headers(),
        json=heartbeat_payload(account_login=account_login),
    )
    assert recovered.status_code == 200
    status_response = client.get("/executor/status", headers=auth_headers())
    assert status_response.status_code == 200
    statuses = status_response.json()["executors"]
    assert any(item["account_login"] == account_login for item in statuses)


def test_tick_ingestion_requires_authentication() -> None:
    response = client.post(
        "/market/ticks",
        json={
            "broker_id": "test-broker",
            "point": 0.01,
            "ticks": [
                {
                    "symbol": "XAUUSD",
                    "bid": 2500.0,
                    "ask": 2500.2,
                    "broker_time": "2026-09-02T00:00:00+00:00",
                    "observed_at": "2026-09-02T00:00:00+00:00",
                }
            ],
        },
    )
    assert response.status_code == 401


def test_tick_ingestion_returns_candidate_but_blocks_uncalibrated_entry(monkeypatch) -> None:
    monkeypatch.setattr(
        calendar_client,
        "context_for",
        lambda *_args, **_kwargs: {"source_health": "HEALTHY", "matched_event": None},
    )
    tick_store.clear()
    with journal.connect() as connection:
        connection.execute("DELETE FROM detector_events")
    bids = [
        2500.00,
        2500.01,
        2500.00,
        2499.99,
        2500.00,
        2500.01,
        2500.00,
        2499.99,
        2490.00,
        2492.00,
        2495.00,
        2497.00,
        2498.00,
        2498.50,
    ]
    ticks = [
        {
            "symbol": "XAUUSD",
            "bid": bid,
            "ask": bid + 0.20,
            "broker_time": f"2026-09-02T00:00:{index:02d}+00:00",
            "observed_at": f"2026-09-02T00:00:{index:02d}+00:00",
        }
        for index, bid in enumerate(bids)
    ]
    response = client.post(
        "/market/ticks",
        headers=auth_headers(),
        json={"broker_id": "test-broker", "point": 0.01, "ticks": ticks},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["accepted_ticks"] == 14
    assert body["detector"]["candidate"]["direction"] == "BUY"
    assert body["detector"]["candidate"]["reversal_confirmed"] is True
    assert body["probability_status"] == "NOT_CALIBRATED"
    assert body["entry_eligible"] is False
    assert body["shadow_event_recorded"] is True

    events = client.get("/shadow/events", headers=auth_headers()).json()
    assert events["count"] >= 1
    assert events["events"][0]["label_status"] == "PENDING"

    target_tick = {
        "symbol": "XAUUSD",
        "bid": 2500.20,
        "ask": 2500.40,
        "broker_time": "2026-09-02T00:00:14+00:00",
        "observed_at": "2026-09-02T00:00:14+00:00",
    }
    labelled = client.post(
        "/market/ticks",
        headers=auth_headers(),
        json={
            "broker_id": "test-broker",
            "point": 0.01,
            "ticks": [target_tick],
        },
    )
    assert labelled.status_code == 200
    assert labelled.json()["shadow_outcomes_labelled"] == 1
    events = client.get("/shadow/events", headers=auth_headers()).json()["events"]
    target_events = [event for event in events if event["label_status"] == "TARGET_HIT"]
    assert len(target_events) == 1
    assert target_events[0]["outcome"]["pricing_side"] == "BID"


def test_incidents_endpoint_is_authenticated() -> None:
    assert client.get("/incidents").status_code == 401
    response = client.get("/incidents", headers=auth_headers())
    assert response.status_code == 200
    assert "incidents" in response.json()


def test_readiness_distinguishes_telemetry_from_entry_readiness() -> None:
    tick_store.clear()
    with journal.connect() as connection:
        connection.execute("DELETE FROM executor_status")

    empty = client.get("/telemetry/readiness", headers=auth_headers())
    assert empty.status_code == 200
    assert empty.json()["telemetry_ready"] is False
    assert "EXECUTOR_NOT_SEEN" in empty.json()["blockers"]
    assert "TICK_STREAM_NOT_SEEN" in empty.json()["blockers"]

    heartbeat = client.post(
        "/executor/heartbeat",
        headers=auth_headers(),
        json=heartbeat_payload(account_login=991001),
    )
    assert heartbeat.status_code == 200
    now = datetime.now(UTC).isoformat()
    ticks = client.post(
        "/market/ticks",
        headers=auth_headers(),
        json={
            "broker_id": "MetaQuotes Ltd.|MetaQuotes-Demo",
            "point": 0.01,
            "ticks": [
                {
                    "symbol": "XAUUSD",
                    "bid": 2500.0,
                    "ask": 2500.2,
                    "broker_time": now,
                    "observed_at": now,
                }
            ],
        },
    )
    assert ticks.status_code == 200

    ready = client.get("/telemetry/readiness", headers=auth_headers()).json()
    assert ready["telemetry_ready"] is True
    assert ready["entry_ready"] is False
    assert ready["blockers"] == ["PROBABILITY_MODEL_NOT_READY"]


def test_readiness_requires_authentication() -> None:
    assert client.get("/telemetry/readiness").status_code == 401


def test_shadow_metrics_reports_all_modes_without_claiming_calibration() -> None:
    with journal.connect() as connection:
        connection.execute("DELETE FROM detector_events")
    for event_id, outcome in (("metric-target", "TARGET_HIT"), ("metric-stop", "STOP_HIT")):
        journal.record_detector_event(
            event_id=event_id,
            broker_id="test-broker",
            symbol="XAUUSD",
            strategy_mode="REGULAR_MISMATCH",
            direction="BUY",
            confirmed=True,
            spread_artifact=False,
            detector_version="mismatch-v0.1.0",
            input_hash=f"sha256:{event_id}",
            payload={"event_id": event_id},
        )
        assert journal.label_detector_event(
            event_id=event_id,
            outcome=outcome,
            payload={"outcome": outcome},
        )

    response = client.get("/shadow/metrics", headers=auth_headers())
    assert response.status_code == 200
    body = response.json()
    assert len(body["modes"]) == 3
    regular = next(
        mode for mode in body["modes"] if mode["strategy_mode"] == "REGULAR_MISMATCH"
    )
    assert regular["resolved_outcomes"] == 2
    assert regular["observed_target_rate"] == 0.5
    assert regular["wilson_95_interval"] == [0.094529, 0.905471]
    assert regular["sample_gate_met"] is False
    assert body["all_sample_gates_met"] is False
    assert body["probability_model_ready"] is False
    assert body["calibration_ready"] is False
    assert "not calibrated probabilities" in body["notice"]


def test_shadow_metrics_requires_authentication() -> None:
    assert client.get("/shadow/metrics").status_code == 401
