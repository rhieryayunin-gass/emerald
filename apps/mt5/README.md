# MT5 Executor

`RIRI_EMERALD_DEMO_v1_203.mq5` is a new, independent EA written specifically for
EMERALD. It does not reuse or modify the RIRI Executor. Install only v1.203 on the EMERALD demo chart. v1.202 is retained for source
history and has a known broker-time/UTC timestamp defect.

The current build:

- refuses every account except a MetaQuotes-Demo, USD, XAUUSD, hedging account
  with leverage 1:200;
- persists start-of-day equity and equity high-water mark;
- enforces a 20% Jakarta-day loss stop and a manually reset 50% high-water
  drawdown hard stop locally;
- enforces the 0.50 managed-volume ceiling;
- closes regular EMERALD positions before the broker-reported session end;
- preserves only dedicated rollover positions whose comments start with
  `EMR|ROLL|`;
- streams genuine Bid/Ask ticks to `/market/ticks` using `CopyTicks`;
- sends validated health/account telemetry to `/executor/heartbeat`;
- enters fail-safe and deletes pending entries when the API heartbeat expires;
- never opens a position independently.

Before use, add `https://api-emerald.albiagent.com` to MT5's **Allow WebRequest
for listed URL** setting. The EA refuses localhost and
`api-riri.albiagent.com`, preventing accidental telemetry submission to RIRI.
`WebRequest` does not run in Strategy Tester, so API integration must be tested
on the MetaQuotes demo terminal. The command-polling and signed-command protocol
will only be enabled after the probability model is calibrated.


## Timestamp contract in v1.203

The EA estimates the broker offset from `TimeTradeServer() - TimeGMT()`, rounded
to 15 minutes, and rejects an implausible offset. It subtracts the offset from
`MqlTick.time_msc` before formatting `broker_time` as UTC. `observed_at` is the
actual UTC acquisition time after `CopyTicks`, rather than a copy of broker time.
The raw broker-time cursor and broker trading-session calculations stay unchanged.
The payload declares `timestamp_contract=utc-v1` and the applied broker offset;
the backend must not subtract that offset a second time.

Synchronize Windows date/time before running. This depends on the terminal's clock
and must be verified on the demo terminal, including any broker DST change.
`TimeGMT()` equals simulated server time in Strategy Tester; this telemetry build
refuses to infer an offset there. Offline source tests do not compile MQL5.

Deploy the v0.5 backend, then replace the EA on the chart with a newly compiled
v1.203. Keep the same MagicNumber and existing risk inputs; persisted risk state
is preserved. Keep only one EMERALD EA on the chart/account. The API rejects old
future-dated ticks with `MARKET_TIMESTAMP_AHEAD_OF_SERVER`, visible in incidents.
Verify that the latest broker and observed UTC times are close to real UTC,
and that `tick_age_seconds` reflects actual freshness. New events use detector
version `mismatch-v0.5.0-utc`; old journal rows are retained unchanged.
