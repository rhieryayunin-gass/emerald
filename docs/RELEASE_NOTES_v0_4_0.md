# RIRI EMERALD v0.4.0

- Shadow detector relaxed to collect more reversal candidates.
- Adds `EXPLORATORY` tier for candidates that fail the standard shadow confirmation.
- Daily 04:00–05:00 WIB rollover uses a dedicated, more permissive detector and is labelled `ROLLOVER_EXPLORATORY`.
- Tier is persisted and displayed in the journal.

These tiers are dataset collection only. Demo lock, entry lock, probability gate, risk ceilings, and fail-safe remain unchanged.
