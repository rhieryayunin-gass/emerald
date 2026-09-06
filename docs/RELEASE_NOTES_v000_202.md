# RIRI EMERALD Shadow Build v000.202

This package advances the demo project from telemetry-only foundations to a
measurable shadow-outcome pipeline. It does not enable order entry.

## Included

- The unchanged demo-only MT5 EA `RIRI_EMERALD_DEMO_v000_201.mq5`.
- Bid/Ask-aware labels for confirmed BUY and SELL reversal candidates.
- Structural entry, stop, target, and confirmation-time validation.
- Target-first, stop-first, and censored outcome persistence.
- Dataset metrics for all four EMERALD strategy modes.
- Minimum resolved-sample gate of 100 outcomes per mode by default.
- Wilson 95% intervals shown as descriptive statistics, never as calibrated
  probabilities.
- Updated Windows telemetry checker with shadow metrics.

## Safety state

- `EMERALD_PROBABILITY_MODEL_READY=false` remains the default.
- Confirmed detector candidates still return `entry_eligible=false`.
- The EA has no order-command polling protocol and cannot open trades from the
  Brain API.
- Local daily-loss and high-water hard-stop protections remain active in MT5.

## Verification

- Ruff: passed.
- Pytest: 73 passed.
- Python coverage: 92% overall.
- MetaEditor result supplied by the user: code generated, 0 errors, 1 known
  private-build version metadata warning.
