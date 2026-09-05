from emerald.journal import SQLiteJournal


def test_sqlite_journal_records_decisions_and_incidents(tmp_path) -> None:
    journal = SQLiteJournal(tmp_path / "journal.db")
    journal.initialize()
    journal.record_decision(
        decision_id="d1",
        setup_id="s1",
        thesis_id="t1",
        strategy_mode="REGULAR_MISMATCH",
        action="NONE",
        model_version="champion-001",
        input_hash="sha256:test",
        payload={"reason": "probability too low"},
    )
    journal.record_incident(
        incident_id="i1",
        severity="HIGH",
        component="AI_TRADER",
        code="AI_HEARTBEAT_EXPIRED",
        status="OPEN",
        details={"age_seconds": 20},
    )

    with journal.connect() as connection:
        decision_count = connection.execute("SELECT COUNT(*) FROM decisions").fetchone()[0]

    assert decision_count == 1
    incidents = journal.list_open_incidents()
    assert len(incidents) == 1
    assert incidents[0]["code"] == "AI_HEARTBEAT_EXPIRED"


def test_detector_events_are_idempotent_and_pending_labelling(tmp_path) -> None:
    journal = SQLiteJournal(tmp_path / "journal.db")
    journal.initialize()
    values = {
        "event_id": "event-1",
        "broker_id": "broker-a",
        "symbol": "XAUUSD",
        "direction": "BUY",
        "confirmed": True,
        "spread_artifact": False,
        "detector_version": "mismatch-v0.1.0",
        "input_hash": "sha256:test",
        "payload": {"extreme_time": "2026-09-02T00:00:08+00:00"},
    }
    assert journal.record_detector_event(**values) is True
    assert journal.record_detector_event(**values) is False
    events = journal.list_detector_events()
    assert len(events) == 1
    assert events[0]["label_status"] == "PENDING"


def test_filtered_detector_event_can_be_promoted_and_labelled(tmp_path) -> None:
    journal = SQLiteJournal(tmp_path / "journal.db")
    journal.initialize()
    values = {
        "event_id": "event-promote",
        "broker_id": "broker-a",
        "symbol": "XAUUSD",
        "direction": "BUY",
        "spread_artifact": False,
        "detector_version": "mismatch-v0.1.0",
        "input_hash": "sha256:one",
        "payload": {"reversal_confirmed": False},
        "label_status": "FILTERED",
    }
    assert journal.record_detector_event(confirmed=False, **values) is True
    values["input_hash"] = "sha256:two"
    values["payload"] = {"reversal_confirmed": True}
    values["label_status"] = "PENDING"
    assert journal.record_detector_event(confirmed=True, **values) is True
    pending = journal.list_pending_detector_events(broker_id="BROKER-A", symbol="xauusd")
    assert len(pending) == 1
    assert pending[0]["confirmed"] == 1
    assert journal.label_detector_event(
        event_id="event-promote",
        outcome="TARGET_HIT",
        payload={"pnl_points": 180.0},
    ) is True
    assert journal.label_detector_event(
        event_id="event-promote",
        outcome="TARGET_HIT",
        payload={"pnl_points": 180.0},
    ) is False
    assert journal.list_detector_events()[0]["label_status"] == "TARGET_HIT"


def test_executor_status_upserts_and_incident_resolves(tmp_path) -> None:
    journal = SQLiteJournal(tmp_path / "journal.db")
    journal.initialize()
    previous = journal.record_executor_status(
        account_login=123,
        account_server="MetaQuotes-Demo",
        system_state="FAIL_SAFE",
        incident_code="API_DOWN",
        payload={"equity": 3000.0},
    )
    assert previous is None
    previous = journal.record_executor_status(
        account_login=123,
        account_server="MetaQuotes-Demo",
        system_state="ACTIVE",
        incident_code="NONE",
        payload={"equity": 2990.0},
    )
    assert previous == "API_DOWN"
    assert journal.list_executor_statuses()[0]["system_state"] == "ACTIVE"

    journal.upsert_incident(
        incident_id="incident-1",
        severity="HIGH",
        component="MT5_EXECUTOR",
        code="API_DOWN",
        details={"account_login": 123},
    )
    assert len(journal.list_open_incidents()) == 1
    journal.resolve_incident("incident-1")
    assert journal.list_open_incidents() == []
