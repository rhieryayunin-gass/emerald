from __future__ import annotations

import math
import warnings
from collections import Counter, defaultdict
from datetime import datetime, timedelta
from statistics import mean

from emerald.evaluation.metrics import wilson_interval

from .dataset import COHORT_FIELDS, FEATURES, Sample, prepare
from .model import SCHEMA, predict, seal


def partition(samples: list[Sample]) -> tuple[list[Sample], list[Sample], list[Sample], int]:
    """Chronological 60/20/20; purge labels not available at the next partition start."""
    first = int(len(samples) * 0.6)
    second = int(len(samples) * 0.8)
    train, calibrate, test = samples[:first], samples[first:second], samples[second:]
    before = len(train) + len(calibrate)
    if calibrate:
        train = [sample for sample in train if sample.available_at < calibrate[0].start]
    if test:
        calibrate = [sample for sample in calibrate if sample.available_at < test[0].start]
    return train, calibrate, test, before - len(train) - len(calibrate)


def fit_model(train: list[Sample], calibrate: list[Sample]) -> dict:
    # Optional dependency, imported only by the offline runner, never by tick ingestion.
    import numpy as np
    from sklearn.exceptions import ConvergenceWarning
    from sklearn.linear_model import LogisticRegression
    from sklearn.preprocessing import StandardScaler

    x = np.asarray([sample.x for sample in train])
    scaler = StandardScaler().fit(x)
    with warnings.catch_warnings():
        warnings.simplefilter("error", ConvergenceWarning)
        base = LogisticRegression(C=1.0, max_iter=2000, random_state=0)
        base.fit(scaler.transform(x), [sample.y for sample in train])
        scores = base.decision_function(scaler.transform([sample.x for sample in calibrate]))
        sigmoid = LogisticRegression(C=1.0, max_iter=2000, random_state=0)
        sigmoid.fit(scores.reshape(-1, 1), [sample.y for sample in calibrate])
    return {
        "algorithm": "standardized_logistic_with_disjoint_sigmoid",
        "mean": scaler.mean_.tolist(),
        "scale": scaler.scale_.tolist(),
        "coefficients": base.coef_[0].tolist(),
        "intercept": float(base.intercept_[0]),
        "sigmoid_coefficient": float(sigmoid.coef_[0, 0]),
        "sigmoid_intercept": float(sigmoid.intercept_[0]),
        "feature_min": x.min(axis=0).tolist(),
        "feature_max": x.max(axis=0).tolist(),
    }


def reliability(probabilities: list[float], labels: list[int]) -> tuple[list[dict], float]:
    bins = []
    error = 0.0
    for index in range(5):
        members = [
            (p, y)
            for p, y in zip(probabilities, labels, strict=True)
            if min(4, int(p * 5)) == index
        ]
        if not members:
            continue
        predicted = mean(p for p, _ in members)
        observed = mean(y for _, y in members)
        error += len(members) * abs(predicted - observed) / len(labels)
        bins.append(
            {
                "lower": index / 5,
                "upper": (index + 1) / 5,
                "samples": len(members),
                "mean_probability": predicted,
                "target_rate": observed,
                "wilson_95_interval": wilson_interval(sum(y for _, y in members), len(members)),
            }
        )
    return bins, error


def evaluate(model: dict, train: list[Sample], test: list[Sample], cost: float | None) -> dict:
    probabilities = [predict(model, sample.x) for sample in test]
    raw = [predict(model, sample.x, calibrated=False) for sample in test]
    labels = [sample.y for sample in test]
    baseline = mean(sample.y for sample in train)
    bins, ece = reliability(probabilities, labels)
    brier = mean((p - y) ** 2 for p, y in zip(probabilities, labels, strict=True))
    baseline_brier = mean((baseline - y) ** 2 for y in labels)
    selected = []
    for sample, p in zip(test, probabilities, strict=True):
        support = all(
            low <= value <= high
            for low, value, high in zip(
                model["feature_min"], sample.x, model["feature_max"], strict=True
            )
        )
        ev = (
            None if cost is None else p * sample.reward_points - (1 - p) * sample.risk_points - cost
        )
        if p >= 0.8 and support and ev is not None and ev > 0:
            selected.append((sample, p, ev))
    count = len(selected)
    successes = sum(sample.y for sample, _, _ in selected)
    # Targets are capped at their specified level; stop gaps retain their full adverse fill.
    net_returns = (
        [(min(s.pnl_points, s.reward_points) - cost) / s.risk_points for s, _, _ in selected]
        if cost is not None
        else []
    )
    curve = peak = drawdown = 0.0
    for value in net_returns:
        curve += value
        peak = max(peak, curve)
        drawdown = max(drawdown, peak - curve)
    low, high = wilson_interval(successes, count)
    # A conservative fixed-cost stress: lowest reward and largest observed stop loss.
    conservative_ev = None
    if selected and cost is not None:
        conservative_ev = (
            low * min(s.reward_points for s, _, _ in selected)
            - (1 - low) * max(max(s.risk_points, -s.pnl_points) for s, _, _ in selected)
            - cost
        )
    return {
        "test_samples": len(test),
        "brier_score": brier,
        "baseline_brier_score": baseline_brier,
        "raw_brier_score": mean((p - y) ** 2 for p, y in zip(raw, labels, strict=True)),
        "log_loss": -mean(
            y * math.log(max(p, 1e-12)) + (1 - y) * math.log(max(1 - p, 1e-12))
            for p, y in zip(probabilities, labels, strict=True)
        ),
        "calibration_error": ece,
        "reliability_bins": bins,
        "selected_samples": count,
        "selected_target_rate": successes / count if count else None,
        "selected_wilson_95_interval": [low, high],
        "mean_net_r": mean(net_returns) if net_returns else None,
        "maximum_drawdown_r": drawdown if net_returns else None,
        "conservative_ev_points": conservative_ev,
        "test_predictions": [
            {"event_id": s.event_id, "probability": p, "label": s.y}
            for s, p in zip(test, probabilities, strict=True)
        ],
    }


def build_report(rows: list[dict], dataset_sha: str, now: datetime, cost: float | None) -> dict:
    if cost is not None and (not math.isfinite(cost) or cost < 0):
        raise ValueError("additional costs must be finite and nonnegative")
    samples, audit, incomplete = prepare(rows, now)
    groups = defaultdict(list)
    for sample in samples:
        groups[sample.cohort].append(sample)
    cohorts = []
    for key, group in sorted(groups.items()):
        required = 100 if key[2] == "REGULAR_MISMATCH" else 20
        train, calibrate, test, purged = partition(group)
        blockers = []
        item = {
            "key": key,
            **dict(zip(COHORT_FIELDS, key, strict=True)),
            "usable_samples": len(group),
            "minimum_samples": required,
            "split_counts": {
                "train": len(train),
                "calibration": len(calibrate),
                "test": len(test),
                "purged": purged,
            },
            "split_ids": {
                "train": [s.event_id for s in train],
                "calibration": [s.event_id for s in calibrate],
                "test": [s.event_id for s in test],
            },
            "model": None,
            "validation": None,
        }
        if len(group) < required:
            blockers.append("INSUFFICIENT_INDEPENDENT_SAMPLES")
        if len(train) < 10 or len(calibrate) < 4 or len(test) < 4:
            blockers.append("INSUFFICIENT_TIME_SPLIT")
        if any(
            Counter(s.y for s in part)[label] < 2 for part in (train, calibrate) for label in (0, 1)
        ):
            blockers.append("INSUFFICIENT_CLASS_COVERAGE")
        # Report incomplete historical opportunities, instead of counting only quick resolved wins.
        if any(
            tuple(event["cohort"]) == key and group[0].start <= event["start"] <= group[-1].end
            for event in incomplete
        ):
            blockers.append("INCOMPLETE_HISTORICAL_OUTCOMES")
        if not any(
            reason in blockers
            for reason in ("INSUFFICIENT_TIME_SPLIT", "INSUFFICIENT_CLASS_COVERAGE")
        ):
            model = fit_model(train, calibrate)
            validation = evaluate(model, train, test, cost)
            item["model"], item["validation"] = model, validation
            if validation["brier_score"] >= validation["baseline_brier_score"]:
                blockers.append("NO_OUT_OF_TIME_PROBABILITY_SKILL")
            if validation["calibration_error"] > 0.10:
                blockers.append("CALIBRATION_ERROR_ABOVE_10_PERCENT")
            if validation["selected_samples"] < 4:
                blockers.append("INSUFFICIENT_80_PERCENT_VALIDATION_SIGNALS")
            if (validation["selected_target_rate"] or 0) < 0.8:
                blockers.append("VALIDATION_TARGET_RATE_BELOW_80_PERCENT")
            if validation["mean_net_r"] is None or validation["mean_net_r"] <= 0:
                blockers.append("NONPOSITIVE_VALIDATION_EXPECTANCY")
            if (
                validation["conservative_ev_points"] is None
                or validation["conservative_ev_points"] <= 0
            ):
                blockers.append("UNCERTAIN_EXPECTANCY_AFTER_COSTS")
        if cost is None:
            blockers.append("EXECUTION_COSTS_NOT_CONFIGURED")
        item["blockers"] = blockers
        item["status"] = "VALIDATED_FOR_DEMO_REVIEW" if not blockers else "REJECTED"
        cohorts.append(item)
    eligible = sum(item["status"] == "VALIDATED_FOR_DEMO_REVIEW" for item in cohorts)
    return seal(
        {
            "schema": SCHEMA,
            "features": list(FEATURES),
            "created_at": now.isoformat(),
            "expires_at": (now + timedelta(days=7)).isoformat(),
            "dataset_sha256": dataset_sha,
            "audit": audit,
            "cohorts": cohorts,
            "eligible_cohorts": eligible,
            "status": "DEMO_REVIEW_READY" if eligible else "REJECTED",
            "data_quality_blockers": (
                ["MARKET_CLOCK_AHEAD_OF_LABEL_CLOCK"]
                if audit["invalid_resolved_reasons"].get("MARKET_CLOCK_AHEAD_OF_LABEL_CLOCK")
                else []
            ),
            "missing_modes": sorted(
                {"REGULAR_MISMATCH", "ROLLOVER_REVERSAL", "NEWS_REVERSAL"}
                - {key[2] for key in groups}
            ),
            "execution_enabled": False,
            "real_trading_allowed": False,
            "policy": {
                "minimum_probability": 0.8,
                "minimum_regular_samples": 100,
                "minimum_special_samples": 20,
                "time_split": [0.6, 0.2, 0.2],
                "additional_cost_points": cost,
                "maximum_calibration_error": 0.10,
                "minimum_selected_test_samples": 4,
                "hyperparameter_search": False,
            },
            "limitations": [
                "One chronological holdout is an initial evaluation, not proof of an 80% future win rate.",
                "Small special-mode cohorts may fit a candidate but cannot bypass validation.",
                "Bid/Ask spread is embedded in labels; additional costs cover commissions and round-trip slippage.",
                "Unobserved intra-batch/outage ticks cannot be reconstructed from historical event summaries.",
                "Repeated tuning against the same holdout invalidates its independence; use new data for the next review.",
                "No EA order-entry protocol or account-specific risk approval is enabled by this report.",
            ],
        }
    )
