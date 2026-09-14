from pathlib import Path

from .model import load_report


def calibration_status(path: Path) -> dict:
    base = {
        "probability_model_ready": False,
        "entry_ready": False,
        "execution_enabled": False,
        "real_trading_allowed": False,
    }
    if not path.is_file():
        return {
            **base,
            "status": "NOT_RUN",
            "blockers": ["CALIBRATION_REPORT_NOT_FOUND"],
            "cohorts": [],
        }
    try:
        report = load_report(path)
    except (ValueError, OSError, KeyError, TypeError, OverflowError):
        return {
            **base,
            "status": "INVALID_OR_EXPIRED",
            "blockers": ["CALIBRATION_REPORT_INVALID_OR_EXPIRED"],
            "cohorts": [],
        }
    cohorts = [
        {k: v for k, v in item.items() if k not in {"model", "split_ids"}}
        for item in report["cohorts"]
    ]
    for item in cohorts:
        if item["validation"]:
            item["validation"] = {
                k: v for k, v in item["validation"].items() if k != "test_predictions"
            }
    return {
        **base,
        "status": report["status"],
        "artifact_id": report["artifact_id"],
        "created_at": report["created_at"],
        "expires_at": report["expires_at"],
        "dataset_sha256": report["dataset_sha256"],
        "audit": report["audit"],
        "policy": report["policy"],
        "cohorts": cohorts,
        "missing_modes": report["missing_modes"],
        "eligible_cohorts": report["eligible_cohorts"],
        "probability_model_ready": report["eligible_cohorts"] > 0,
        "blockers": ["EXECUTION_PROTOCOL_NOT_IMPLEMENTED"]
        + ([] if report["eligible_cohorts"] else ["NO_VALIDATED_COHORT"]),
    }
