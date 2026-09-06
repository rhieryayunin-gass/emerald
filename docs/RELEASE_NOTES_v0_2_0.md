# RIRI EMERALD v0.2.0

This release changes EMERALD from a Windows-local telemetry package into an
independent production-style demo stack. It does not enable automated entries.

## Independent stack

- New private Next.js dashboard for `emerald.albiagent.com`.
- Dedicated FastAPI endpoint target `api-emerald.albiagent.com`.
- Dedicated VPS service `riri-emerald-api` bound to port `8010`.
- Dedicated release, environment, and database paths under the
  `riri-emerald` namespace.
- Guardrails prevent the deployment scripts and EA from targeting RIRI paths,
  service names, domains, or port 8000.

## Dashboard

- Server-side proxy keeps the API bearer token out of browser JavaScript.
- Password login with a signed HttpOnly session cookie.
- Five-second refresh for telemetry, XAUUSD Bid/Ask, incidents, risk controls,
  shadow events, and calibration maturity.
- All timestamps render in GMT+7 / Asia-Jakarta.

## Executor

- New `RIRI_EMERALD_DEMO_v1_202.mq5` production-telemetry build.
- Defaults to the dedicated HTTPS EMERALD API.
- Refuses localhost and `api-riri.albiagent.com`.
- Remains demo-account-only and retains local risk fallback.
- Order command polling remains absent while probability calibration is locked.

## Verification

- Python lint passed.
- 79 Python tests passed with 92% coverage.
- Next.js 16 production build and TypeScript checks passed.
- Authenticated frontend-to-backend smoke test passed with telemetry ready and
  entry/calibration correctly locked.
