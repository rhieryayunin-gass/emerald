# RIRI EMERALD

RIRI EMERALD is a separate XAUUSD **Mismatch Reversal Specialist**. It uses a
deterministic detector, calibrated probability model, contextual AI Trader,
hard Risk Engine, and an MT5 executor with local fail-safe controls.

This repository intentionally does not alter or deploy the existing RIRI
project.

## Locked safety boundaries

- Demo account only by default.
- Minimum calibrated probability: 80%.
- Positive expected value after costs is mandatory.
- Regular setup risk: dynamic, maximum 10%.
- Rollover/news setup risk: dynamic, maximum 5%.
- Aggregate gross open risk: maximum 10%.
- Daily loss hard stop: 20%.
- Overall drawdown hard stop: 50% from high-water mark.
- Maximum 2 independent theses and 5 tranches per thesis.
- Equity-tier lot ceiling, maximum total volume 0.50 lot.
- No new entries during AI/API failure.

## Local development

```bash
uv sync --extra dev
uv run pytest
uv run uvicorn apps.brain_api.main:app --reload
```

Local execution is for automated development tests only. The active deployment
target is a fully separate EMERALD stack:

| Component | EMERALD target | Existing RIRI boundary |
| --- | --- | --- |
| Frontend | `emerald.albiagent.com` | Never deploy to `albiagent.com` |
| Backend | `api-emerald.albiagent.com` | Never deploy to `api-riri.albiagent.com` |
| Vercel project | `riri-emerald-dashboard` | Separate project and secrets |
| VPS service | `riri-emerald-api` on `127.0.0.1:8010` | Does not modify `riri-api` |
| VPS root | `/opt/riri-emerald` | Does not use `/opt/riri` or `/opt/riri-releases` |
| Database | `/var/lib/riri-emerald/emerald.db` | Separate journal and permissions |

The current milestone implements the locked domain contract, hard Risk Engine,
strategy/system state machines, local fail-safe decision logic, API and MT5 EA
foundations, Bid/Ask tick ingestion, spread-artifact filtering, executable-price
outcome labelling, and an idempotent shadow-event journal.

Detector output is intentionally named `detector_score`, not probability. A
candidate cannot become entry-eligible until a separately calibrated
statistical model supplies the locked minimum 80% probability and positive
expected value after trading costs.

`GET /shadow/metrics` reports target/stop outcomes, unresolved and censored
samples, observed target rate, and a Wilson 95% interval for each strategy mode.
These descriptive dataset metrics are explicitly not treated as calibrated
probabilities. Regular mismatch requires 100 resolved outcomes; rollover and
news reversal each require 20. The Monday-gap category is removed because the
documented pattern is the daily 04:00–05:00 WIB rollover window. Passing a
sample gate still does not enable trading unless
the separately validated probability model is explicitly marked ready.

The Windows demo executor is `apps/mt5/RIRI_EMERALD_DEMO_v1_202.mq5`. It is a new
EMERALD-only implementation locked to the MetaQuotes-Demo profile documented in
`docs/METAQUOTES_DEMO_PROFILE.md`. It contains no real-account override and no
order-entry protocol yet; the current deployment stage is telemetry and shadow
data collection.

The EA rejects localhost and the existing RIRI API, and defaults to the dedicated
HTTPS EMERALD endpoint. `scripts/windows/Check-EmeraldProduction.ps1` checks the
remote service while requesting the API token through a secure prompt.

The independent Next.js dashboard lives in `apps/dashboard`. Its server-side
route holds the backend credential; the credential is not included in browser
JavaScript. Dashboard access also requires its own password and signed HttpOnly
session cookie.
