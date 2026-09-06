import sqlite3

import pytest

from emerald.evaluation import wilson_interval
from emerald.journal import SQLiteJournal


def test_wilson_interval_handles_empty_and_observed_samples() -> None:
    assert wilson_interval(0, 0) == (0.0, 1.0)
    assert wilson_interval(8, 10) == (0.490157, 0.943319)
    assert wilson_interval(10, 10) == (0.72246, 1.0)
    assert wilson_interval(0, 10) == (0.0, 0.27754)


@pytest.mark.parametrize(
    ("successes", "observations", "z_score"),
    [
        (-1, 10, 1.96),
        (11, 10, 1.96),
        (0, -1, 1.96),
        (0, 0, 0.0),
        (0, 0, float("nan")),
    ],
)
def test_wilson_interval_rejects_invalid_inputs(
    successes: int,
    observations: int,
    z_score: float,
) -> None:
    with pytest.raises(ValueError):
        wilson_interval(successes, observations, z_score)


def test_detector_metrics_are_grouped_by_strategy_mode(tmp_path) -> None:
    journal = SQLiteJournal(tmp_path / "journal.db")
    journal.initialize()
    cases = [
        ("regular-target", "REGULAR_MISMATCH", True, "TARGET_HIT"),
        ("regular-stop", "REGULAR_MISMATCH", True, "STOP_HIT"),
        ("regular-pending", "REGULAR_MISMATCH", True, None),
        ("news-filtered", "NEWS_REVERSAL", False, "FILTERED"),
        ("news-censored", "NEWS_REVERSAL", True, "CENSORED"),
    ]
    for event_id, strategy_mode, confirmed, outcome in cases:
        journal.record_detector_event(
            event_id=event_id,
            broker_id="broker-a",
            symbol="XAUUSD",
            strategy_mode=strategy_mode,
            direction="BUY",
            confirmed=confirmed,
            spread_artifact=False,
            detector_version="mismatch-v0.1.0",
            input_hash=f"sha256:{event_id}",
            payload={"event_id": event_id},
            label_status="FILTERED" if outcome == "FILTERED" else "PENDING",
        )
        if outcome in {"TARGET_HIT", "STOP_HIT", "CENSORED"}:
            assert journal.label_detector_event(
                event_id=event_id,
                outcome=outcome,
                payload={"outcome": outcome},
            )

    metrics = {row["strategy_mode"]: row for row in journal.detector_metrics_by_mode()}
    assert metrics["REGULAR_MISMATCH"] == {
        "strategy_mode": "REGULAR_MISMATCH",
        "total_events": 3,
        "confirmed_events": 3,
        "pending_events": 1,
        "target_hits": 1,
        "stop_hits": 1,
        "censored_events": 0,
        "filtered_events": 0,
    }
    assert metrics["NEWS_REVERSAL"]["total_events"] == 2
    assert metrics["NEWS_REVERSAL"]["censored_events"] == 1
    assert metrics["NEWS_REVERSAL"]["filtered_events"] == 1


def test_initialize_migrates_legacy_detector_table(tmp_path) -> None:
    database = tmp_path / "legacy.db"
    with sqlite3.connect(database) as connection:
        connection.execute(
            """
            CREATE TABLE detector_events (
                event_id TEXT PRIMARY KEY,
                broker_id TEXT NOT NULL,
                symbol TEXT NOT NULL,
                direction TEXT NOT NULL,
                confirmed INTEGER NOT NULL,
                spread_artifact INTEGER NOT NULL,
                detector_version TEXT NOT NULL,
                input_hash TEXT NOT NULL,
                payload_json TEXT NOT NULL,
                label_status TEXT NOT NULL DEFAULT 'PENDING',
                outcome_json TEXT,
                created_at TEXT NOT NULL,
                labelled_at TEXT
            )
            """
        )
        connection.execute(
            """
            INSERT INTO detector_events (
                event_id, broker_id, symbol, direction, confirmed, spread_artifact,
                detector_version, input_hash, payload_json, label_status, created_at
            ) VALUES ('legacy-1', 'broker-a', 'XAUUSD', 'BUY', 1, 0,
                      'legacy', 'sha256:legacy', '{}', 'PENDING', '2026-09-02T00:00:00Z')
            """
        )

    journal = SQLiteJournal(database)
    journal.initialize()
    events = journal.list_detector_events()
    assert events[0]["strategy_mode"] == "REGULAR_MISMATCH"
