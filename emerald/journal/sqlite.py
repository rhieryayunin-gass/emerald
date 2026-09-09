from __future__ import annotations

import json
import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

SCHEMA = """
PRAGMA journal_mode=WAL;
PRAGMA foreign_keys=ON;

CREATE TABLE IF NOT EXISTS decisions (
    decision_id TEXT PRIMARY KEY,
    setup_id TEXT NOT NULL,
    thesis_id TEXT NOT NULL,
    strategy_mode TEXT NOT NULL,
    action TEXT NOT NULL,
    model_version TEXT NOT NULL,
    input_hash TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS risk_evaluations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    decision_id TEXT NOT NULL,
    status TEXT NOT NULL,
    approved_risk_fraction REAL NOT NULL,
    approved_lot REAL NOT NULL,
    reasons_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    FOREIGN KEY(decision_id) REFERENCES decisions(decision_id)
);

CREATE TABLE IF NOT EXISTS incidents (
    incident_id TEXT PRIMARY KEY,
    severity TEXT NOT NULL,
    component TEXT NOT NULL,
    code TEXT NOT NULL,
    status TEXT NOT NULL,
    details_json TEXT NOT NULL,
    started_at TEXT NOT NULL,
    resolved_at TEXT
);

CREATE TABLE IF NOT EXISTS detector_events (
    event_id TEXT PRIMARY KEY,
    broker_id TEXT NOT NULL,
    symbol TEXT NOT NULL,
    strategy_mode TEXT NOT NULL DEFAULT 'REGULAR_MISMATCH',
    shadow_tier TEXT NOT NULL DEFAULT 'STANDARD',
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
);

CREATE TABLE IF NOT EXISTS executor_status (
    account_login INTEGER PRIMARY KEY,
    account_server TEXT NOT NULL,
    system_state TEXT NOT NULL,
    incident_code TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    received_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS system_state_transitions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    previous_state TEXT NOT NULL,
    new_state TEXT NOT NULL,
    reason TEXT NOT NULL,
    actor TEXT NOT NULL,
    created_at TEXT NOT NULL
);
"""


def now_iso() -> str:
    return datetime.now(UTC).isoformat()


class SQLiteJournal:
    """Small durable foundation; production storage can implement the same contract."""

    def __init__(self, path: str | Path) -> None:
        self.path = str(path)

    def connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path)
        connection.row_factory = sqlite3.Row
        return connection

    def initialize(self) -> None:
        with self.connect() as connection:
            connection.executescript(SCHEMA)
            columns = {
                row["name"]
                for row in connection.execute("PRAGMA table_info(detector_events)").fetchall()
            }
            if "strategy_mode" not in columns:
                connection.execute(
                    """
                    ALTER TABLE detector_events
                    ADD COLUMN strategy_mode TEXT NOT NULL DEFAULT 'REGULAR_MISMATCH'
                    """
                )
            if "shadow_tier" not in columns:
                connection.execute("ALTER TABLE detector_events ADD COLUMN shadow_tier TEXT NOT NULL DEFAULT 'STANDARD'")
            connection.execute(
                "UPDATE detector_events SET strategy_mode=\'ROLLOVER_REVERSAL\' "
                "WHERE strategy_mode=\'MONDAY_GAP_REVERSAL\'"
            )

    def record_decision(
        self,
        *,
        decision_id: str,
        setup_id: str,
        thesis_id: str,
        strategy_mode: str,
        action: str,
        model_version: str,
        input_hash: str,
        payload: dict[str, Any],
    ) -> None:
        with self.connect() as connection:
            connection.execute(
                """
                INSERT INTO decisions (
                    decision_id, setup_id, thesis_id, strategy_mode, action,
                    model_version, input_hash, payload_json, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    decision_id,
                    setup_id,
                    thesis_id,
                    strategy_mode,
                    action,
                    model_version,
                    input_hash,
                    json.dumps(payload, default=str, sort_keys=True, separators=(",", ":")),
                    now_iso(),
                ),
            )

    def record_incident(
        self,
        *,
        incident_id: str,
        severity: str,
        component: str,
        code: str,
        status: str,
        details: dict[str, Any],
    ) -> None:
        with self.connect() as connection:
            connection.execute(
                """
                INSERT INTO incidents (
                    incident_id, severity, component, code, status,
                    details_json, started_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    incident_id,
                    severity,
                    component,
                    code,
                    status,
                    json.dumps(details, default=str, sort_keys=True, separators=(",", ":")),
                    now_iso(),
                ),
            )

    def list_open_incidents(self) -> list[dict[str, Any]]:
        with self.connect() as connection:
            rows = connection.execute(
                """
                SELECT * FROM incidents
                WHERE resolved_at IS NULL AND status != 'RESOLVED'
                ORDER BY started_at DESC
                """
            ).fetchall()
        return [dict(row) for row in rows]

    def record_detector_event(
        self,
        *,
        event_id: str,
        broker_id: str,
        symbol: str,
        strategy_mode: str = "REGULAR_MISMATCH",
        shadow_tier: str = "STANDARD",
        direction: str,
        confirmed: bool,
        spread_artifact: bool,
        detector_version: str,
        input_hash: str,
        payload: dict[str, Any],
        label_status: str = "PENDING",
    ) -> bool:
        """Record once, or promote the same extreme from filtered to confirmed."""
        with self.connect() as connection:
            cursor = connection.execute(
                """
                INSERT INTO detector_events (
                    event_id, broker_id, symbol, strategy_mode, shadow_tier, direction, confirmed,
                    spread_artifact, detector_version, input_hash, payload_json,
                    label_status, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(event_id) DO UPDATE SET
                    confirmed=excluded.confirmed,
                    spread_artifact=excluded.spread_artifact,
                    detector_version=excluded.detector_version,
                    input_hash=excluded.input_hash,
                    payload_json=excluded.payload_json,
                    label_status=excluded.label_status
                WHERE detector_events.confirmed=0 AND excluded.confirmed=1
                """,
                (
                    event_id,
                    broker_id,
                    symbol,
                    strategy_mode,
                    shadow_tier,
                    direction,
                    int(confirmed),
                    int(spread_artifact),
                    detector_version,
                    input_hash,
                    json.dumps(payload, default=str, sort_keys=True, separators=(",", ":")),
                    label_status,
                    now_iso(),
                ),
            )
            return cursor.rowcount == 1

    def list_detector_events(self, limit: int = 100) -> list[dict[str, Any]]:
        if limit < 1 or limit > 10_000:
            raise ValueError("limit must be between 1 and 10000")
        with self.connect() as connection:
            rows = connection.execute(
                """
                SELECT * FROM detector_events
                ORDER BY created_at DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
        return [dict(row) for row in rows]

    def list_pending_detector_events(
        self,
        *,
        broker_id: str,
        symbol: str,
    ) -> list[dict[str, Any]]:
        with self.connect() as connection:
            rows = connection.execute(
                """
                SELECT * FROM detector_events
                WHERE lower(broker_id)=lower(?) AND upper(symbol)=upper(?)
                  AND confirmed=1 AND label_status='PENDING'
                ORDER BY created_at ASC
                """,
                (broker_id, symbol),
            ).fetchall()
        return [dict(row) for row in rows]

    def label_detector_event(
        self,
        *,
        event_id: str,
        outcome: str,
        payload: dict[str, Any],
    ) -> bool:
        if outcome not in {"TARGET_HIT", "STOP_HIT", "CENSORED"}:
            raise ValueError("unsupported detector outcome")
        with self.connect() as connection:
            cursor = connection.execute(
                """
                UPDATE detector_events
                SET label_status=?, outcome_json=?, labelled_at=?
                WHERE event_id=? AND label_status='PENDING'
                """,
                (
                    outcome,
                    json.dumps(payload, default=str, sort_keys=True, separators=(",", ":")),
                    now_iso(),
                    event_id,
                ),
            )
        return cursor.rowcount == 1

    def detector_metrics_by_mode(self) -> list[dict[str, Any]]:
        with self.connect() as connection:
            rows = connection.execute(
                """
                SELECT
                    strategy_mode,
                    COUNT(*) AS total_events,
                    SUM(CASE WHEN confirmed=1 THEN 1 ELSE 0 END) AS confirmed_events,
                    SUM(CASE WHEN label_status='PENDING' THEN 1 ELSE 0 END) AS pending_events,
                    SUM(CASE WHEN label_status='TARGET_HIT' THEN 1 ELSE 0 END) AS target_hits,
                    SUM(CASE WHEN label_status='STOP_HIT' THEN 1 ELSE 0 END) AS stop_hits,
                    SUM(CASE WHEN label_status='CENSORED' THEN 1 ELSE 0 END) AS censored_events,
                    SUM(CASE WHEN label_status='FILTERED' THEN 1 ELSE 0 END) AS filtered_events
                FROM detector_events
                GROUP BY strategy_mode
                ORDER BY strategy_mode
                """
            ).fetchall()
        return [dict(row) for row in rows]

    def record_executor_status(
        self,
        *,
        account_login: int,
        account_server: str,
        system_state: str,
        incident_code: str,
        payload: dict[str, Any],
    ) -> str | None:
        """Upsert latest executor status and return its previous incident code."""
        with self.connect() as connection:
            previous = connection.execute(
                "SELECT incident_code FROM executor_status WHERE account_login = ?",
                (account_login,),
            ).fetchone()
            connection.execute(
                """
                INSERT INTO executor_status (
                    account_login, account_server, system_state, incident_code,
                    payload_json, received_at
                ) VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(account_login) DO UPDATE SET
                    account_server=excluded.account_server,
                    system_state=excluded.system_state,
                    incident_code=excluded.incident_code,
                    payload_json=excluded.payload_json,
                    received_at=excluded.received_at
                """,
                (
                    account_login,
                    account_server,
                    system_state,
                    incident_code,
                    json.dumps(payload, default=str, sort_keys=True, separators=(",", ":")),
                    now_iso(),
                ),
            )
        return str(previous["incident_code"]) if previous else None

    def list_executor_statuses(self) -> list[dict[str, Any]]:
        with self.connect() as connection:
            rows = connection.execute(
                "SELECT * FROM executor_status ORDER BY received_at DESC"
            ).fetchall()
        return [dict(row) for row in rows]

    def upsert_incident(
        self,
        *,
        incident_id: str,
        severity: str,
        component: str,
        code: str,
        details: dict[str, Any],
    ) -> None:
        with self.connect() as connection:
            connection.execute(
                """
                INSERT INTO incidents (
                    incident_id, severity, component, code, status,
                    details_json, started_at, resolved_at
                ) VALUES (?, ?, ?, ?, 'OPEN', ?, ?, NULL)
                ON CONFLICT(incident_id) DO UPDATE SET
                    severity=excluded.severity,
                    component=excluded.component,
                    code=excluded.code,
                    status='OPEN',
                    details_json=excluded.details_json,
                    resolved_at=NULL
                """,
                (
                    incident_id,
                    severity,
                    component,
                    code,
                    json.dumps(details, default=str, sort_keys=True, separators=(",", ":")),
                    now_iso(),
                ),
            )

    def resolve_incident(self, incident_id: str) -> None:
        with self.connect() as connection:
            connection.execute(
                """
                UPDATE incidents
                SET status='RESOLVED', resolved_at=?
                WHERE incident_id=? AND status!='RESOLVED'
                """,
                (now_iso(), incident_id),
            )
