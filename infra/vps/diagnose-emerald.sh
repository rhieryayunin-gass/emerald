#!/usr/bin/env bash
# Read-only diagnostics. Never prints the API token or modifies service/database state.
set -euo pipefail
if [[ "${EUID}" -ne 0 ]]; then
  echo "Run: sudo -n bash infra/vps/diagnose-emerald.sh" >&2
  exit 1
fi
set -a
source /etc/riri-emerald/emerald.env
set +a

systemctl --no-pager show riri-emerald-api -p ActiveState -p SubState -p NRestarts -p MemoryCurrent
python3 - <<'PY'
import json
import os
import sqlite3
import time
import urllib.error
import urllib.request
from contextlib import closing
from datetime import UTC, datetime
from pathlib import Path

print("UTC", datetime.now(UTC).isoformat(), flush=True)
token = os.environ["EMERALD_API_TOKEN"]
probes = [
    ("local", "http://127.0.0.1:8010", path)
    for path in ("/health", "/telemetry/readiness", "/shadow/events?limit=50", "/shadow/metrics")
] + [
    ("public", "https://api-emerald.albiagent.com", path)
    for path in ("/health", "/shadow/events?limit=50")
]
for scope, base, path in probes:
    headers = {"Host": "api-emerald.albiagent.com"}
    if path != "/health":
        headers["Authorization"] = f"Bearer {token}"
    request = urllib.request.Request(base + path, headers=headers)
    started = time.perf_counter()
    result = {"scope": scope, "path": path}
    try:
        with urllib.request.urlopen(request, timeout=6) as response:
            result["http_status"] = response.status
            body = response.read()
        result["bytes"] = len(body)
        data = json.loads(body)
        if path == "/health":
            result["version"] = data.get("version")
        elif path == "/telemetry/readiness":
            result["telemetry_ready"] = data.get("telemetry_ready")
            result["blockers"] = data.get("blockers")
            result["tick_streams"] = [
                {key: stream.get(key) for key in ("symbol", "tick_age_seconds", "healthy")}
                for stream in data.get("tick_streams", [])
            ]
        elif path.startswith("/shadow/events"):
            result["event_count"] = data.get("count")
    except urllib.error.HTTPError as error:
        result["http_status"] = error.code
    except Exception as error:
        # No request headers, tokens, or server response bodies in shared output.
        result["error_type"] = type(error).__name__
    result["elapsed_ms"] = round((time.perf_counter() - started) * 1000)
    print(json.dumps(result), flush=True)

path = Path(os.environ.get("EMERALD_JOURNAL_PATH", "/var/lib/riri-emerald/emerald.db"))
if not path.is_absolute():
    path = Path("/opt/riri-emerald/current") / path
with closing(sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True, timeout=3)) as db:
    print("detector_indexes", [row[1] for row in db.execute("PRAGMA index_list(detector_events)")])
    queries = [
        ("recent", "SELECT * FROM detector_events ORDER BY created_at DESC LIMIT 50"),
        ("pending", "SELECT * FROM detector_events WHERE lower(broker_id)=lower('probe') "
         "AND upper(symbol)=upper('XAUUSD') AND confirmed=1 AND label_status='PENDING' "
         "ORDER BY created_at ASC"),
    ]
    for name, sql in queries:
        print("query_plan", name, [row[3] for row in db.execute("EXPLAIN QUERY PLAN " + sql)])
PY

journalctl -u riri-emerald-api -n 60 --no-pager
