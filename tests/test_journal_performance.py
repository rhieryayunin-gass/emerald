import sqlite3
from contextlib import closing

import pytest

from emerald.journal.sqlite import SCHEMA, SQLiteJournal


def populate(connection, count=5000):
    connection.executemany(
        """INSERT INTO detector_events (
            event_id, broker_id, symbol, direction, confirmed, spread_artifact,
            detector_version, input_hash, payload_json, label_status, created_at
        ) VALUES (?, 'Broker-A', 'XAUUSD', 'BUY', ?, 0, 'test', 'hash', '{}', ?, ?)""",
        ((str(i), int(i % 100 == 0), "PENDING" if i % 100 == 0 else "FILTERED",
          f"{i:09}") for i in range(count)),
    )


@pytest.mark.parametrize("operation", ["recent", "pending", "metrics"])
def test_hot_reads_use_indexes_without_sorting_history(tmp_path, monkeypatch, operation):
    journal = SQLiteJournal(tmp_path / "journal.db")
    journal.initialize()
    with closing(journal.connect()) as connection, connection:
        populate(connection)

    original_connect = journal.connect
    statements = []

    def traced_connect():
        connection = original_connect()
        connection.set_trace_callback(statements.append)
        return connection

    monkeypatch.setattr(journal, "connect", traced_connect)
    if operation == "recent":
        rows = journal.list_detector_events(50)
        assert [row["event_id"] for row in rows] == [str(i) for i in range(4999, 4949, -1)]
    elif operation == "pending":
        rows = journal.list_pending_detector_events(broker_id="BROKER-A", symbol="xauusd")
        assert [row["event_id"] for row in rows] == [str(i) for i in range(0, 5000, 100)]
    else:
        rows = journal.detector_metrics_by_mode()
        assert len(rows) == 1
        assert rows[0]["total_events"] == 5000
        assert rows[0]["confirmed_events"] == rows[0]["pending_events"] == 50
        assert rows[0]["filtered_events"] == 4950

    # Inspect the SQL actually issued by the public methods, not a duplicate query.
    selects = [sql for sql in statements if sql.lstrip().upper().startswith("SELECT")]
    assert selects
    with closing(original_connect()) as connection:
        for sql in selects:
            details = [row["detail"] for row in connection.execute("EXPLAIN QUERY PLAN " + sql)]
            assert not any("TEMP B-TREE" in detail for detail in details), details
            assert all("SCAN detector_events" not in detail or "USING" in detail
                       for detail in details), details


@pytest.mark.parametrize("missing", [("shadow_tier",), ("strategy_mode", "shadow_tier")])
def test_index_migration_preserves_legacy_rows_and_is_repeatable(tmp_path, missing):
    journal = SQLiteJournal(tmp_path / "legacy.db")
    legacy_schema = "\n".join(line for line in SCHEMA.splitlines()
                              if not any(line.strip().startswith(name + " TEXT")
                                         for name in missing))
    # decisions.strategy_mode is unrelated to this migration and need not be used.
    with closing(journal.connect()) as connection, connection:
        connection.executescript(legacy_schema)
        populate(connection, count=2)
    journal.initialize()
    journal.initialize()
    rows = journal.list_detector_events()
    assert len(rows) == 2
    assert all(row["strategy_mode"] == "REGULAR_MISMATCH" for row in rows)
    assert all(row["shadow_tier"] == "STANDARD" for row in rows)
    assert rows[0]["payload_json"] == "{}"
    assert rows[1]["label_status"] == "PENDING"


def test_internal_connections_close_on_success_and_sql_error(tmp_path, monkeypatch):
    journal = SQLiteJournal(tmp_path / "journal.db")
    original_connect = journal.connect
    opened = []

    def tracked_connect():
        connection = original_connect()
        opened.append(connection)
        return connection

    monkeypatch.setattr(journal, "connect", tracked_connect)
    journal.initialize()
    journal.list_detector_events()
    values = {"incident_id": "same", "severity": "HIGH", "component": "TEST",
              "code": "TEST", "status": "OPEN", "details": {}}
    journal.record_incident(**values)
    with pytest.raises(sqlite3.IntegrityError):
        journal.record_incident(**values)
    assert len(journal.list_open_incidents()) == 1
    for connection in opened:
        with pytest.raises(sqlite3.ProgrammingError, match="closed"):
            connection.execute("SELECT 1")
