# Architecture Notes

The authoritative product and risk specification is the RIRI EMERALD Master
Blueprint. This repository begins with an implementation that keeps the domain
and Risk Engine independent from FastAPI, databases, LLM providers, and MT5.

That separation allows the hard gates and fail-safe behavior to be tested even
when external services are unavailable.

## Decision path

```text
MT5 + event feeds
  -> versioned live snapshots
  -> mismatch detector
  -> calibrated probability and EV
  -> contextual AI Trader
  -> deterministic Hard Risk Engine
  -> idempotent execution command
  -> MT5 executor
  -> reconciliation and journal
```

The MT5 executor never receives permission to create an independent trading
thesis. During an AI/API outage it blocks new entries and manages existing risk
only through deterministic local controls.

## Phase-2 market path

`POST /market/ticks` accepts ordered, timezone-aware Bid and Ask quotes. Tick
history is bounded, broker-specific, and idempotent for overlapping retries.
The mismatch detector evaluates joint Bid/Ask displacement and reclaim; a
one-sided move or extreme spread expansion is classified as a spread artifact.

Every detector candidate is written once to `detector_events` with its strategy
mode, input hash, detector version, confirmation time, structural stop/target,
and executable entry reference. Filtered candidates can be promoted when the
same extreme later receives valid reversal confirmation.

Pending BUY outcomes are evaluated on Bid and pending SELL outcomes on Ask, using
only ticks after confirmation. The journal labels target-first, stop-first, or
censored outcomes atomically. This prevents spread-only moves and pre-confirmation
prices from contaminating the future training labels.

`GET /shadow/metrics` aggregates dataset maturity separately for
REGULAR_MISMATCH, ROLLOVER_REVERSAL, NEWS_REVERSAL, and MONDAY_GAP_REVERSAL. It
shows the observed target rate and Wilson 95% interval, but never presents those
descriptive values as calibrated model probability. Until a probability model
passes independent validation, the API returns
`probability_status=NOT_CALIBRATED` and `entry_eligible=false` even for a
technically confirmed candidate.
