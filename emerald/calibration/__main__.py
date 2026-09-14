"""Run with: uv run --extra calibration python -m emerald.calibration --help."""

from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import sqlite3
import sys
from datetime import UTC, datetime
from pathlib import Path

from .dataset import read_snapshot
from .model import atomic_write
from .train import build_report


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Calibrate EMERALD shadow events without enabling orders"
    )
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--database", type=Path)
    source.add_argument("--snapshot", type=Path, help="Exported EMERALD shadow JSON or JSON.gz")
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument(
        "--additional-cost-points",
        type=float,
        default=None,
        help="Round-trip slippage and commission per trade, excluding embedded Bid/Ask spread",
    )
    args = parser.parse_args()
    try:
        if args.database:
            rows, digest = read_snapshot(args.database)
        else:
            opener = gzip.open if args.snapshot.suffix == ".gz" else open
            with opener(args.snapshot, "rt") as stream:
                snapshot = json.load(stream)
            if snapshot.get("format") != "emerald-shadow-export-v1":
                raise ValueError("unsupported snapshot")
            rows = snapshot["events"]
            if not isinstance(rows, list):
                raise ValueError("invalid event collection")
            digest = hashlib.sha256(
                json.dumps(rows, sort_keys=True, separators=(",", ":")).encode()
            ).hexdigest()
        report = build_report(rows, digest, datetime.now(UTC), args.additional_cost_points)
        args.output_dir.mkdir(parents=True, exist_ok=True)
        path = args.output_dir / f"calibration-{report['artifact_id'][:16]}.json"
        atomic_write(path, report)
        atomic_write(args.output_dir / "latest.json", report)
        print(
            json.dumps(
                {
                    "status": report["status"],
                    "artifact_id": report["artifact_id"],
                    "audit": report["audit"],
                    "eligible_cohorts": report["eligible_cohorts"],
                    "report_file": str(path),
                    "execution_enabled": False,
                },
                indent=2,
            )
        )
        return 0
    except (
        OSError,
        ValueError,
        TypeError,
        KeyError,
        ImportError,
        RuntimeError,
        sqlite3.Error,
        Warning,
    ) as error:
        # Do not log database payloads, secrets or model data on an execution failure.
        print(
            f"Calibration failed ({type(error).__name__}). No readiness change was applied.",
            file=sys.stderr,
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
