# MT5 Executor

`RIRI_EMERALD_DEMO_v1_202.mq5` is a new, independent EA written specifically for
EMERALD. It does not reuse or modify the RIRI Executor. This is the only EA file
that should be installed for the EMERALD demo account.

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
