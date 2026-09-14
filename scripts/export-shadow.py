#!/usr/bin/env python3
"""Standalone exporter, including on an older installed EMERALD release. No secrets."""

import argparse
import gzip
import json
import sqlite3
from datetime import UTC, datetime
from pathlib import Path

parser = argparse.ArgumentParser(description="Export only EMERALD detector events")
parser.add_argument("--database", type=Path, required=True)
parser.add_argument("--output", type=Path, required=True)
args = parser.parse_args()
with sqlite3.connect(args.database.resolve().as_uri() + "?mode=ro", uri=True, timeout=10) as db:
    db.row_factory = sqlite3.Row
    db.execute("BEGIN")
    columns = {item["name"] for item in db.execute("PRAGMA table_info(detector_events)")}
    allowed = {
        "event_id",
        "broker_id",
        "symbol",
        "strategy_mode",
        "shadow_tier",
        "direction",
        "confirmed",
        "spread_artifact",
        "detector_version",
        "input_hash",
        "payload_json",
        "label_status",
        "outcome_json",
        "created_at",
        "labelled_at",
    }
    if not {"event_id", "payload_json", "label_status"}.issubset(columns):
        raise SystemExit("Not an EMERALD shadow database")
    selected = sorted(allowed & columns)
    events = [
        dict(row)
        for row in db.execute(
            "SELECT " + ",".join(selected) + " FROM detector_events ORDER BY event_id"
        )
    ]
# Exclusive create prevents overwriting an earlier snapshot.
with args.output.open("xb") as raw, gzip.GzipFile(fileobj=raw, mode="wb") as output:
    output.write(
        json.dumps(
            {
                "format": "emerald-shadow-export-v1",
                "exported_at": datetime.now(UTC).isoformat(),
                "columns": selected,
                "events": events,
            },
            separators=(",", ":"),
        ).encode()
    )
print(f"Exported {len(events)} detector events to {args.output}")
