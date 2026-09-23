# Telemetry and dashboard timeout investigation

Reported symptoms: EA v1.203 `/market/ticks` status 1003 with terminal error
4006 and an empty response, plus dashboard `/shadow/events?limit=50` unreachable.
The earlier readiness snapshot was healthy; it does not rule out intermittent
failures. The RIRI_EXECUTOR log belongs to the separate RIRI application.

## Confirmed code defects

- Latest-event reads sort the entire detector table; pending-outcome reads on
  every tick batch also scan historical payloads. No supporting indexes existed.
- `with sqlite3_connection` commits/rolls back but does not close the connection.
- v1.203 reads `GetLastError()` after converting the response array, which can
  replace the original WebRequest error when that array is empty. Error 4006
  means an invalid array; the old log alone cannot identify the original cause.
- The dashboard uses a 4.5-second deadline. Its generic unreachable message
  does not distinguish timeout, transport, or response-decoding failures.

## Changes

Three additive indexes cover recent events, confirmed pending events (with
case-insensitive broker/symbol expressions), and aggregate metrics. They are
installed after legacy-column migrations, are idempotent, and do not delete or
relabel events. Journal methods close their connections after commit/rollback.

EA v1.204 captures the request error immediately, guards empty response decoding,
checks request encoding, and logs duration and byte counts. It retains v1.203's
UTC normalization, 2500 ms timeout, local risk rules, and disabled order entry.
Install only one EMERALD EA; v1.203 is retained for history.

## Evidence and limits

A synthetic 500,000-row local SQLite journal with approximately 1.5 KB payloads
showed a latest-50 read falling from 1.3413 seconds to 0.0009 seconds, and pending
reads from 0.3425 seconds to 0.0010 seconds. These are local measurements, not VPS
latencies or a guarantee of recovery. Tests inspect the query plans emitted by
the actual journal methods, preserve row order/case-insensitive matching/counts,
exercise legacy migration twice, and verify closure after success and SQL error.

EA checks are source-level only: MetaEditor compilation and live WebRequest
validation are still required. HTTP status 1003 is outside normal HTTP status
ranges and is treated as a transport diagnostic, not as an API HTTP response.

## Deployment and diagnosis

Run `sudo -n bash infra/vps/diagnose-emerald.sh` on the VPS before and after
installing the patch. It times localhost and public requests, shows query plans
and recent EMERALD logs, and prints no API token or event payload. It performs no
restart, recalibration, database write, or RIRI action.

Deploy this branch with the existing EMERALD release script. Index creation runs
once at startup and may take longer on a large journal. If startup exceeds the
release script's 20 checks, inspect the service logs before rerunning anything.
Check `/telemetry/readiness` and endpoint latencies after startup. The database
must retain its original ownership; do not remove it or bypass calibration.

Compile `apps/mt5/RIRI_EMERALD_DEMO_v1_204.mq5`, preserve the existing EMERALD
inputs and MagicNumber, and replace v1.203 on its chart. If failures recur, share
the new `category`, `status`, `terminal_error`, `elapsed_ms`, and byte-count log.
Verify the public API is in MT5's allowed WebRequest list and compare Windows
connectivity with VPS measurements. No frontend redeployment is required for
these backend/EA fixes. Keep automatic entries locked.
