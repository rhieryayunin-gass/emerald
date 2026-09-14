import copy
import hashlib
import json
import math
import sqlite3
import subprocess
import sys
from datetime import UTC, datetime, timedelta

import pytest

from emerald.calibration.dataset import features, prepare, read_snapshot
from emerald.calibration.model import atomic_write, evaluate_event, load_report, predict
from emerald.calibration.status import calibration_status
from emerald.calibration.train import build_report, partition


def shadow_rows(count=180, *, mode="ROLLOVER_REVERSAL", tier="ROLLOVER_EXPLORATORY"):
    start = datetime.now(UTC) - timedelta(days=20)
    rows = []
    for i in range(count):
        at = start + timedelta(minutes=i * 5)
        win = i % 3 != 0
        state = "TARGET_HIT" if win else "STOP_HIT"
        # Synthetic separable prices are software test data, never market evidence.
        payload = {
            "extreme_time": (at - timedelta(seconds=2)).isoformat(),
            "confirmed_at": at.isoformat(),
            "entry_reference": 2500.0,
            "structural_target": 2502.0,
            "structural_invalidation": 2499.0,
            "reversal_confirmed": True,
            "spread_artifact": False,
            "detector_score": 1.0,
            "displacement_points": 500.0 if win else 80.0,
            "displacement_zscore": 8 if win else 2,
            "reclaim_fraction": 0.5 if win else 0.3,
            "baseline_spread_points": 20,
            "peak_spread_points": 21 if win else 70,
        }
        event_id = f"sample-{i}"
        resolved = at + timedelta(seconds=30)
        outcome = {
            "event_id": event_id,
            "outcome": state,
            "confirmed_at": at.isoformat(),
            "resolved_at": resolved.isoformat(),
            "entry_reference": 2500.0,
            "pricing_side": "BID",
            "risk_points": 100.0,
            "reward_points": 200.0,
            "pnl_points": 200.0 if win else -100.0,
        }
        rows.append(
            {
                "event_id": event_id,
                "broker_id": "metaquotes ltd.|metaquotes-demo",
                "symbol": "XAUUSD",
                "strategy_mode": mode,
                "shadow_tier": tier,
                "direction": "BUY",
                "detector_version": "mismatch-v0.4.0",
                "confirmed": 1,
                "spread_artifact": 0,
                "input_hash": hashlib.sha256(event_id.encode()).hexdigest(),
                "payload_json": json.dumps(payload),
                "outcome_json": json.dumps(outcome),
                "label_status": state,
                "created_at": at.isoformat(),
                "labelled_at": resolved.isoformat(),
            }
        )
    return rows


def report_for(rows=None, cost=2.0):
    return build_report(
        shadow_rows() if rows is None else rows, "fixture-not-market-data", datetime.now(UTC), cost
    )


def test_complete_calibration_is_reproducible_and_runtime_uses_same_model(tmp_path):
    rows = shadow_rows()
    now = datetime.now(UTC)
    report = build_report(rows, "fixture", now, 2.0)
    assert report == build_report(rows, "fixture", now, 2.0)
    assert report["eligible_cohorts"] == 1
    assert report["execution_enabled"] is False
    item = report["cohorts"][0]
    assert item["status"] == "VALIDATED_FOR_DEMO_REVIEW"
    assert item["validation"]["brier_score"] < item["validation"]["baseline_brier_score"]
    train, calibrate, test = (
        set(item["split_ids"][name]) for name in ("train", "calibration", "test")
    )
    assert not (train & calibrate or train & test or calibrate & test)
    path = tmp_path / "latest.json"
    atomic_write(path, report)
    loaded = load_report(path)
    event = {**rows[1], "payload": json.loads(rows[1]["payload_json"])}
    result = evaluate_event(loaded, event, point=0.01)
    assert result["calibrated_probability"] > 0.8
    assert result["model_gate_passed"] is True
    assert result["entry_eligible"] is False
    assert (
        predict(loaded["cohorts"][0]["model"], features(event["payload"], "BUY"))
        == result["calibrated_probability"]
    )
    event["shadow_tier"] = "EXPLORATORY"
    assert evaluate_event(loaded, event, point=0.01)["status"] == "COHORT_NOT_CALIBRATED"
    event["shadow_tier"] = rows[1]["shadow_tier"]
    event["payload"]["displacement_points"] = 1e9
    assert not evaluate_event(loaded, event, point=0.01)["model_gate_passed"]


def test_score_one_is_not_used_as_probability_and_late_regime_failure_is_rejected():
    rows = shadow_rows()
    for row in rows[144:]:
        state = "STOP_HIT" if row["label_status"] == "TARGET_HIT" else "TARGET_HIT"
        row["label_status"] = state
        outcome = json.loads(row["outcome_json"])
        outcome.update(outcome=state, pnl_points=200 if state == "TARGET_HIT" else -100)
        row["outcome_json"] = json.dumps(outcome)
    report = report_for(rows)
    assert report["eligible_cohorts"] == 0
    assert "NO_OUT_OF_TIME_PROBABILITY_SKILL" in report["cohorts"][0]["blockers"]


def test_missing_costs_fit_probabilities_but_do_not_pass_readiness():
    report = report_for(cost=None)
    item = report["cohorts"][0]
    assert item["model"] is not None
    assert report["eligible_cohorts"] == 0
    assert "EXECUTION_COSTS_NOT_CONFIGURED" in item["blockers"]


@pytest.mark.parametrize("cost", [-1, float("nan"), float("inf")])
def test_invalid_costs_rejected(cost):
    with pytest.raises(ValueError):
        report_for(cost=cost)


def test_twenty_special_samples_allow_attempt_but_never_bypass_gates():
    special = report_for(shadow_rows(20))
    item = special["cohorts"][0]
    assert item["minimum_samples"] == 20
    assert "INSUFFICIENT_INDEPENDENT_SAMPLES" not in item["blockers"]
    assert special["eligible_cohorts"] == 0
    regular = report_for(shadow_rows(20, mode="REGULAR_MISMATCH", tier="STANDARD"))
    assert regular["cohorts"][0]["minimum_samples"] == 100
    assert "INSUFFICIENT_INDEPENDENT_SAMPLES" in regular["cohorts"][0]["blockers"]


def test_resolved_events_are_deduplicated_and_overlapping_opportunities_are_purged():
    rows = shadow_rows(4)
    duplicate = copy.deepcopy(rows[1])
    duplicate["event_id"] = "duplicate"
    outcome = json.loads(duplicate["outcome_json"])
    outcome["event_id"] = "duplicate"
    duplicate["outcome_json"] = json.dumps(outcome)
    overlap = copy.deepcopy(duplicate)
    overlap["event_id"], overlap["input_hash"] = "overlap", "different-hash"
    outcome["event_id"] = "overlap"
    overlap["outcome_json"] = json.dumps(outcome)
    overlap["shadow_tier"] = "EXPLORATORY"
    samples, audit, _ = prepare(rows + [duplicate, overlap], datetime.now(UTC))
    assert len(samples) == 4
    assert audit["excluded"]["DUPLICATE_INPUT"] == 1
    assert audit["excluded"]["OVERLAPPING_EPISODE"] == 1


def test_delayed_label_availability_is_purged_at_time_split():
    from dataclasses import replace

    samples, _, _ = prepare(shadow_rows(30), datetime.now(UTC))
    samples[17] = replace(samples[17], available_at=samples[18].start)
    samples[23] = replace(samples[23], available_at=samples[24].start)
    train, cal, test, purged = partition(samples)
    assert purged == 2
    assert all(s.available_at < cal[0].start for s in train)
    assert all(s.available_at < test[0].start for s in cal)


def test_pending_historical_events_block_validation_but_not_recent_unfinished_events():
    rows = shadow_rows()
    rows[100]["label_status"] = "PENDING"
    rows[100]["outcome_json"] = None
    result = report_for(rows)
    assert "INCOMPLETE_HISTORICAL_OUTCOMES" in result["cohorts"][0]["blockers"]


@pytest.mark.parametrize(
    "change", ["nan", "wrong-side", "future-label", "bad-structure", "unconfirmed"]
)
def test_malformed_or_leaking_event_is_excluded(change):
    rows = shadow_rows(1)
    payload, outcome = json.loads(rows[0]["payload_json"]), json.loads(rows[0]["outcome_json"])
    if change == "nan":
        payload["displacement_points"] = math.nan
    elif change == "wrong-side":
        outcome["pricing_side"] = "ASK"
    elif change == "future-label":
        rows[0]["labelled_at"] = (datetime.now(UTC) + timedelta(days=1)).isoformat()
    elif change == "bad-structure":
        payload["structural_invalidation"] = 2501
    else:
        payload["reversal_confirmed"] = False
    rows[0].update(payload_json=json.dumps(payload), outcome_json=json.dumps(outcome))
    samples, audit, _ = prepare(rows, datetime.now(UTC))
    assert not samples
    assert audit["excluded"]["INVALID_RESOLVED_EVENT"] == 1


def test_pre_news_release_cannot_be_used_as_news_reversal():
    rows = shadow_rows(1, mode="NEWS_REVERSAL", tier="STANDARD")
    payload = json.loads(rows[0]["payload_json"])
    payload["classification"] = {
        "news": {
            "source_health": "HEALTHY",
            "fresh": True,
            "matched_event": {
                "currency": "USD",
                "impact": "High",
                "scheduled_at": payload["confirmed_at"],
            },
        }
    }
    rows[0]["payload_json"] = json.dumps(payload)
    assert not prepare(rows, datetime.now(UTC))[0]


def test_atomic_report_checksum_expiry_and_status_fail_closed(tmp_path):
    path = tmp_path / "latest.json"
    assert calibration_status(path)["status"] == "NOT_RUN"
    report = report_for()
    atomic_write(path, report)
    assert calibration_status(path)["probability_model_ready"] is True
    assert calibration_status(path)["entry_ready"] is False
    assert "model" not in calibration_status(path)["cohorts"][0]
    with pytest.raises(ValueError):
        load_report(path, datetime.now(UTC) + timedelta(days=8))
    report["eligible_cohorts"] = 99
    path.write_text(json.dumps(report))
    assert calibration_status(path)["status"] == "INVALID_OR_EXPIRED"
    assert not calibration_status(path)["probability_model_ready"]


def test_readonly_database_and_cli_export_no_account_tables_or_secret(tmp_path):
    from emerald.journal import SQLiteJournal

    db = tmp_path / "journal.db"
    journal = SQLiteJournal(db)
    journal.initialize()
    rows = shadow_rows()
    with sqlite3.connect(db) as conn:
        conn.execute("CREATE TABLE private_tokens (secret TEXT)")
        conn.execute("INSERT INTO private_tokens VALUES ('do-not-export-this')")
        for row in rows:
            conn.execute(
                "INSERT INTO detector_events ("
                + ",".join(row)
                + ") VALUES ("
                + ",".join("?" for _ in row)
                + ")",
                list(row.values()),
            )
    snapshot, digest = read_snapshot(db)
    assert len(snapshot) == len(rows)
    assert "do-not-export-this" not in json.dumps(snapshot)
    assert len(digest) == 64
    output = tmp_path / "calibration"
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "emerald.calibration",
            "--database",
            str(db),
            "--output-dir",
            str(output),
            "--additional-cost-points",
            "2",
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    report = load_report(output / "latest.json")
    assert report["eligible_cohorts"] == 1
    assert "do-not-export-this" not in (output / "latest.json").read_text()
    assert read_snapshot(db)[1] == digest

    exported = tmp_path / "shadow.json.gz"
    export_result = subprocess.run(
        [
            sys.executable,
            "scripts/export-shadow.py",
            "--database",
            str(db),
            "--output",
            str(exported),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert export_result.returncode == 0, export_result.stderr
    from_export = tmp_path / "from-export"
    exported_run = subprocess.run(
        [
            sys.executable,
            "-m",
            "emerald.calibration",
            "--snapshot",
            str(exported),
            "--output-dir",
            str(from_export),
            "--additional-cost-points",
            "2",
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert exported_run.returncode == 0, exported_run.stderr
    exported_report = load_report(from_export / "latest.json")
    assert exported_report["dataset_sha256"] == report["dataset_sha256"]
    assert exported_report["cohorts"] == report["cohorts"]
