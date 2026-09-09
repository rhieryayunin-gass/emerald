# RIRI EMERALD v0.3.0

## Contextual shadow dataset

- Adds a cached high-impact USD economic-calendar context for `NEWS_REVERSAL`.
- Classifies only the post-event context window; a failed/unavailable source never
  creates a guessed news label or unlocks entry.
- Records calendar health and matched-event evidence in each shadow candidate.
- Treats the daily 04:00–05:00 WIB pattern as `ROLLOVER_REVERSAL`; the obsolete
  Monday-only category is migrated into that strategy.
- Uses 100 resolved outcomes for `REGULAR_MISMATCH`, and 20 each for rollover
  and news shadow datasets.

All entry locks, demo-only operation, and deterministic risk controls remain unchanged.
