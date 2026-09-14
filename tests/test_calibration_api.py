from fastapi.testclient import TestClient

from apps.brain_api import main
from emerald.calibration.model import atomic_write
from tests.test_api import heartbeat_payload
from tests.test_probability_calibration import report_for


def headers():
    return {"Authorization": f"Bearer {main.settings.api_token}"}


def test_calibration_endpoints_require_auth_and_do_not_expose_model_on_status(
    monkeypatch, tmp_path
):
    path = tmp_path / "latest.json"
    monkeypatch.setattr(main, "calibration_report_path", path)
    client = TestClient(main.app)
    assert client.get("/calibration/status").status_code == 401
    assert client.get("/calibration/report").status_code == 401
    assert client.get("/calibration/status", headers=headers()).json()["status"] == "NOT_RUN"
    assert client.get("/calibration/report", headers=headers()).status_code == 404
    atomic_write(path, report_for())
    status = client.get("/calibration/status", headers=headers()).json()
    assert status["probability_model_ready"] is True
    assert "model" not in status["cohorts"][0]
    assert status["entry_ready"] is False
    assert client.get("/calibration/report", headers=headers()).json()["cohorts"][0]["model"]
    path.write_text('{"broken":')
    assert client.get("/calibration/report", headers=headers()).status_code == 409
    assert client.get("/health").json()["probability_model_ready"] is False


def test_legacy_flag_cannot_enable_heartbeat_or_readiness(monkeypatch, tmp_path):
    monkeypatch.setattr(main.settings, "probability_model_ready", True)
    monkeypatch.setattr(main, "calibration_report_path", tmp_path / "latest.json")
    client = TestClient(main.app)
    assert client.get("/health").json()["probability_model_ready"] is False
    response = client.post("/executor/heartbeat", headers=headers(), json=heartbeat_payload())
    assert response.json()["new_entries_allowed"] is False
    readiness = client.get("/telemetry/readiness", headers=headers()).json()
    assert readiness["entry_ready"] is False
    assert "EXECUTION_PROTOCOL_NOT_IMPLEMENTED" in readiness["blockers"]


def test_calibrated_report_cannot_enable_orders(monkeypatch, tmp_path):
    path = tmp_path / "latest.json"
    atomic_write(path, report_for())
    monkeypatch.setattr(main, "calibration_report_path", path)
    client = TestClient(main.app)
    assert client.get("/health").json()["probability_model_ready"] is True
    assert (
        client.post("/executor/heartbeat", headers=headers(), json=heartbeat_payload()).json()[
            "new_entries_allowed"
        ]
        is False
    )


def test_promoted_event_updates_tier_and_strategy(tmp_path):
    from emerald.journal import SQLiteJournal

    journal = SQLiteJournal(tmp_path / "events.db")
    journal.initialize()
    common = {
        "event_id": "same-extreme",
        "broker_id": "broker",
        "symbol": "XAUUSD",
        "direction": "BUY",
        "spread_artifact": False,
        "detector_version": "v1",
        "input_hash": "hash",
        "payload": {},
    }
    journal.record_detector_event(**common, confirmed=False, label_status="FILTERED")
    journal.record_detector_event(
        **common,
        confirmed=True,
        strategy_mode="ROLLOVER_REVERSAL",
        shadow_tier="ROLLOVER_EXPLORATORY",
    )
    row = journal.list_detector_events()[0]
    assert row["strategy_mode"] == "ROLLOVER_REVERSAL"
    assert row["shadow_tier"] == "ROLLOVER_EXPLORATORY"


def test_client_probability_cannot_enable_risk_approval(monkeypatch, tmp_path):
    import json
    from dataclasses import asdict

    from tests.fixtures import valid_context, valid_proposal

    monkeypatch.setattr(main.settings, "probability_model_ready", True)
    monkeypatch.setattr(main, "calibration_report_path", tmp_path / "missing.json")
    payload = {"proposal": asdict(valid_proposal()), "context": asdict(valid_context())}
    response = TestClient(main.app).post(
        "/risk/evaluate", headers=headers(), json=json.loads(json.dumps(payload, default=str))
    )
    assert response.status_code == 200
    body = response.json()
    assert body["approved"] is False
    assert body["approved_lot"] == 0
    assert "EXECUTION_PROTOCOL_NOT_IMPLEMENTED" in body["reasons"]
