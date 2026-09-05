from __future__ import annotations

import math


def wilson_interval(successes: int, observations: int, z_score: float = 1.96) -> tuple[float, float]:
    """Return a Wilson score interval without pretending it is model calibration."""
    if observations < 0 or successes < 0 or successes > observations:
        raise ValueError("successes must be between zero and observations")
    if not math.isfinite(z_score) or z_score <= 0:
        raise ValueError("z_score must be finite and positive")
    if observations == 0:
        return 0.0, 1.0
    rate = successes / observations
    denominator = 1.0 + z_score**2 / observations
    center = (rate + z_score**2 / (2.0 * observations)) / denominator
    margin = (
        z_score
        * math.sqrt(
            rate * (1.0 - rate) / observations
            + z_score**2 / (4.0 * observations**2)
        )
        / denominator
    )
    return round(max(0.0, center - margin), 6), round(min(1.0, center + margin), 6)
