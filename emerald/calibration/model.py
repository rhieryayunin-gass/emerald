from __future__ import annotations

import hashlib
import json
import math
import os
import tempfile
from datetime import UTC, datetime
from pathlib import Path

from .dataset import FEATURES, cohort, features, timestamp

SCHEMA = "emerald-calibration-v2"


def sigmoid(value: float) -> float:
    if value >= 0:
        return 1 / (1 + math.exp(-value))
    exp = math.exp(value)
    return exp / (1 + exp)


def predict(model: dict, x: list[float], *, calibrated: bool = True) -> float:
    if len(x) != len(FEATURES) or not all(math.isfinite(v) for v in x):
        raise ValueError("invalid features")
    score = model["intercept"] + sum(
        weight * (value - mean) / scale
        for weight, value, mean, scale in zip(
            model["coefficients"], x, model["mean"], model["scale"], strict=True
        )
    )
    if calibrated:
        score = model["sigmoid_coefficient"] * score + model["sigmoid_intercept"]
    if not math.isfinite(score):
        raise ValueError("invalid model output")
    return sigmoid(score)


def seal(report: dict) -> dict:
    body = {key: value for key, value in report.items() if key != "artifact_id"}
    digest = hashlib.sha256(
        json.dumps(body, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    ).hexdigest()
    return {**body, "artifact_id": digest}


def atomic_write(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix=".calibration-", dir=path.parent)
    try:
        with os.fdopen(fd, "w") as stream:
            json.dump(payload, stream, sort_keys=True, indent=2, allow_nan=False)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(name, path)
    finally:
        if os.path.exists(name):
            os.unlink(name)


def load_report(path: Path, now: datetime | None = None) -> dict:
    now = now or datetime.now(UTC)
    report = json.loads(path.read_text())
    if report.get("schema") != SCHEMA or report.get("features") != list(FEATURES):
        raise ValueError("unsupported calibration artifact")
    if seal(report)["artifact_id"] != report.get("artifact_id"):
        raise ValueError("calibration artifact checksum mismatch")
    if not timestamp(report["created_at"]) <= now < timestamp(report["expires_at"]):
        raise ValueError("calibration artifact expired or future-dated")
    for item in report["cohorts"]:
        model = item.get("model")
        if model is None:
            continue
        for field in ("coefficients", "mean", "scale"):
            if len(model[field]) != len(FEATURES) or not all(
                math.isfinite(v) for v in model[field]
            ):
                raise ValueError("invalid model vector")
        if any(v <= 0 for v in model["scale"]):
            raise ValueError("invalid scaler")
        predict(model, model["mean"])
    return report


def evaluate_event(report: dict, row: dict, *, point: float, now: datetime | None = None) -> dict:
    """Model assessment only. Order construction/risk approval are separate milestones."""
    now = now or datetime.now(UTC)
    if not timestamp(report["created_at"]) <= now < timestamp(report["expires_at"]):
        return {"status": "MODEL_EXPIRED", "model_gate_passed": False}
    key = cohort(row)
    item = next((item for item in report["cohorts"] if tuple(item["key"]) == key), None)
    if not item or not item.get("model"):
        return {"status": "COHORT_NOT_CALIBRATED", "model_gate_passed": False}
    payload = row["payload"]
    if not payload.get("reversal_confirmed") or payload.get("spread_artifact"):
        return {"status": "UNCONFIRMED_EVENT", "model_gate_passed": False}
    if not math.isfinite(point) or point <= 0:
        raise ValueError("invalid point")
    x = features(payload, key[4])
    probability = predict(item["model"], x)
    in_support = all(
        low <= value <= high
        for low, value, high in zip(
            item["model"]["feature_min"], x, item["model"]["feature_max"], strict=True
        )
    )
    reward = abs(payload["structural_target"] - payload["entry_reference"]) / point
    risk = abs(payload["structural_invalidation"] - payload["entry_reference"]) / point
    cost = report["policy"]["additional_cost_points"]
    ev = None if cost is None else probability * reward - (1 - probability) * risk - cost
    passed = (
        item["status"] == "VALIDATED_FOR_DEMO_REVIEW"
        and in_support
        and probability >= report["policy"]["minimum_probability"]
        and ev is not None
        and ev > 0
    )
    return {
        "status": "MODEL_GATE_PASSED" if passed else "MODEL_GATE_REJECTED",
        "artifact_id": report["artifact_id"],
        "calibrated_probability": probability,
        "expected_value_net_points": ev,
        "in_feature_support": in_support,
        "model_gate_passed": passed,
        "entry_eligible": False,
    }
