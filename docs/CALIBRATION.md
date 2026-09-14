# Calibration and the transition from shadow collection

This release provides an offline training/calibration runner and read-only model
assessment. It does **not** implement the MT5 order-entry protocol. A successful
report is a prerequisite for reviewing demo execution, not a command to enable it.
The owner remains the only authority for real-account activation.

## Run on the VPS

Use an updated EMERALD source checkout. From a VPS prompt such as
`rhiery86_ayunin@riri-prod-01`, run:

```bash
cd /home/rhiery86_ayunin/emerald-deploy-source
sudo -n bash infra/vps/calibrate-emerald.sh
sudo -n cat /var/lib/riri-emerald/calibration/latest.json
```

The runner uses a separate Python environment in
`/opt/riri-emerald/calibration-tools/`. It reads only `detector_events` from
`/var/lib/riri-emerald/emerald.db` in one SQLite read transaction. It does not copy
account tables, credentials, or alter the journal. It writes an immutable result
and atomically updates `calibration/latest.json`. No service restart is needed.
It does not call OpenAI or fetch a news feed while training.

The first run may omit costs. Probability fitting and the report still run, but
economic approval is blocked with `EXECUTION_COSTS_NOT_CONFIGURED`. After checking
the broker's round-trip commissions and a slippage assumption, pass their **sum
in symbol points**, excluding spread already embedded in Bid/Ask labels:

```bash
sudo -n bash infra/vps/calibrate-emerald.sh <additional_cost_points>
```

Replace the placeholder with a measured or explicitly agreed value. Do not assume
zero because the account is demo. There is no default fictitious cost estimate.

The runner can be used **before deploying the API/frontend changes**. For API and
dashboard visibility, deploy this release using the existing isolated EMERALD
deployment. The API reads `calibration/latest.json` beside its configured journal;
`EMERALD_CALIBRATION_REPORT_PATH` may specify a different report path. Report
coefficients are JSON, not an executable pickle.

## Export for analysis in another environment

The standalone `scripts/export-shadow.py` works without installing this release:

```bash
sudo -n python3 scripts/export-shadow.py \
  --database /var/lib/riri-emerald/emerald.db \
  --output /home/rhiery86_ayunin/emerald-shadow.json.gz
```

It exports only detector-event fields, excludes account/credential tables, and refuses
an existing output filename. Upload that export for analysis, or run locally:

```bash
uv run --extra calibration python -m emerald.calibration \
  --snapshot /path/to/emerald-shadow.json.gz \
  --output-dir calibration-artifacts
```

The snapshot must be from the real shadow journal. Synthetic fixtures establish
software correctness only and must never be activated or presented as market results.

## What the analysis does

- Uses confirmed, valid target/stop labels with correct executable-price side.
  Rejects malformed, future-dated, spread-only and pre-release news-reversal data.
- Uses continuous displacement, z-score, reclaim, spread expansion and reward/risk
  features available at confirmation. It does not use `detector_score`, which
  saturates at 1 for confirmed candidates. Outcomes are never prediction features.
- Groups by broker, symbol, strategy, tier, direction and detector version.
  Exploratory events are not pooled with standard events.
- Removes duplicate inputs and overlapping broker/symbol episodes. The sample
  count can consequently be lower than the dashboard's historical raw count.
- Uses chronological 60% training, 20% sigmoid calibration, 20% final testing.
  Purges earlier samples whose labels were not available before the next split.
  The scaler is fit only on training data. No refit uses the final holdout.
- Keeps 100 independent samples for regular cohorts and 20 for rollover/news.
  Small cohorts can be evaluated, but insufficient class coverage, time splits,
  or validation evidence keep them rejected. Every strategy may progress independently.
- Reports Brier score vs a training-prior baseline, raw Brier score, log loss,
  reliability bins, calibration error, selected-signal target rate, Wilson interval,
  expectancy and drawdown in R. R drawdown is not an account-equity backtest.
- Evaluates signals at the existing 80% probability threshold and positive net EV.
  Requires at least four selected out-of-time signals, observed target rate >=80%,
  calibration error <=0.10, improvement over the baseline, positive net expectancy
  and positive stressed expectancy using the Wilson lower bound. These are initial
  demo-review checks, not a statistical guarantee of future returns.
- Caps favorable target fills at the target level; preserves adverse stop gaps.
  Existing Bid/Ask spread is retained; additional commission/slippage is deducted.

The method uses regularized logistic regression followed by an independently fitted
sigmoid calibrator. For the rationale for independent calibration data and why Brier
score alone does not prove calibration, see the
[scikit-learn calibration documentation](https://scikit-learn.org/stable/modules/calibration.html).

## Report and API

`GET /calibration/status` and `GET /calibration/report` require the EMERALD API token.
The dashboard displays the evaluated sample counts, separate cohort results,
rejection reasons and a report download. Its signed login session protects downloads;
the backend token stays on the frontend server.

`/market/ticks` can assess a fresh candidate against the same cohort's saved model.
Missing, corrupt, expired, unvalidated or out-of-support models cannot pass its model
gate. `entry_eligible` stays false. Reports expire after seven days; checking the
legacy `EMERALD_PROBABILITY_MODEL_READY` flag does not grant readiness. Heartbeats,
readiness and the risk API explicitly expose the missing execution protocol.

## Remaining work after the actual report

1. Inspect the real-data report and verify additional costs and usable sample counts.
2. Review eligible cohorts, including spread/slippage and data gaps. A final holdout
   repeatedly used for tuning is no longer independent; reserve new data for another
   review instead of changing thresholds until this report passes.
3. Implement and test the demo-only EA order protocol, server-generated proposals,
   order acknowledgement/reconciliation, idempotency, session-close handling, and
   account-specific risk snapshots. The current EA still collects telemetry and
   performs its existing local fail-safe controls.
4. Compile and install that EA on Windows, then verify a full order lifecycle on
   MetaQuotes-Demo before declaring demo execution operational.

Historical summaries cannot reconstruct missing intra-batch ticks, terminal outages,
or the exact live fill latency. Calibration is therefore an initial model evaluation,
not a substitute for execution validation. Pending/censored historical opportunities
are reported and block affected cohorts to avoid selecting only quickly resolved
outcomes. Existing shadow collection can continue as monitoring after this phase.

## Market-time integrity gate

A resolved outcome whose market timestamp is more than five seconds after the
backend `labelled_at` timestamp is excluded as `MARKET_CLOCK_AHEAD_OF_LABEL_CLOCK`.
A historical date alone does not establish clock correctness. The report includes
raw resolved counts and separate invalid-reason counts, and the dashboard displays
the clock problem. Five seconds allows rounding/clock jitter, not timezone offsets.

Do not silently subtract a fixed number of hours from the original journal or
relabel news/rollover cohorts: the permissive detector used at that time was also
selected by that faulty clock. Preserve those rows for audit. Deploy API v0.5 and
EA v1.203 to produce UTC-normalized observations before assessing a new cohort.
The UTC version tag separates the new detector inputs from the legacy model data.

The API rejects timestamps ahead of server reception/acquisition before storing
or labelling anything. Quote freshness uses both event time and acquisition time,
so reading a backlog cannot make an old price healthy. A calendar event must be
released, high-impact USD, and from a fresh healthy feed before it receives a
NEWS_REVERSAL label. Pre-release calendar information remains in context evidence.

Calibration results can reject a strategy even with ample raw records. Review
reward/stop geometry and outcomes after costs before changing a probability gate.
Do not repeatedly tune against the same final holdout or present rejected models
as an automatic transition to demo entries.

The artifact schema is `emerald-calibration-v2`. Earlier reports must be rerun;
they cannot prove that market/label clock integrity was checked.
