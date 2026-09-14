#!/usr/bin/env bash
set -euo pipefail

# This runs offline analysis against a consistent read transaction. It does not restart services.
if [[ "${EUID}" -ne 0 ]]; then
  echo "Run: sudo -n bash infra/vps/calibrate-emerald.sh [additional_cost_points]" >&2
  exit 1
fi
if [[ $# -gt 1 ]]; then
  echo "Expected at most one argument: round-trip costs in points excluding spread." >&2
  exit 1
fi
project_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
if [[ "${project_root}" == "/opt/riri" || "${project_root}" == /opt/riri-releases/* ]]; then
  echo "Refusing existing RIRI path." >&2
  exit 1
fi
if [[ ! -f /etc/riri-emerald/emerald.env ]] ||
   ! grep -qx 'EMERALD_ENVIRONMENT=demo' /etc/riri-emerald/emerald.env ||
   ! grep -qx 'EMERALD_ALLOW_REAL_TRADING=false' /etc/riri-emerald/emerald.env; then
  echo "Expected dedicated EMERALD demo configuration." >&2
  exit 1
fi
database=/var/lib/riri-emerald/emerald.db
if [[ ! -f "$database" ]]; then
  echo "EMERALD journal not found at $database." >&2
  exit 1
fi
if ! [[ -f "${project_root}/emerald/calibration/__main__.py" ]]; then
  echo "Calibration source missing; update the EMERALD checkout first." >&2
  exit 1
fi
id riri-emerald >/dev/null
command -v uv >/dev/null
command -v flock >/dev/null
exec 9>/var/lib/riri-emerald/calibration.lock
flock -n 9 || { echo "Another calibration is running." >&2; exit 1; }
run_id="$(date -u +%Y%m%dT%H%M%SZ)-$$"
tool_dir="/opt/riri-emerald/calibration-tools/${run_id}"
install -d -o root -g root -m 0755 "$tool_dir"
cp "${project_root}/pyproject.toml" "${project_root}/uv.lock" "${project_root}/README.md" "$tool_dir/"
cp -R "${project_root}/emerald" "$tool_dir/emerald"
uv sync --project "$tool_dir" --frozen --no-dev --extra calibration
chmod -R a+rX "$tool_dir"
install -d -o riri-emerald -g riri-emerald -m 0700 /var/lib/riri-emerald/calibration
calibration_args=(--database "$database" --output-dir /var/lib/riri-emerald/calibration)
if [[ $# -eq 1 ]]; then
  calibration_args+=(--additional-cost-points "$1")
fi
cd "$tool_dir"
# Limit training CPU to one thread on the shared VPS.
runuser -u riri-emerald -- env OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 MKL_NUM_THREADS=1 \
  "$tool_dir/.venv/bin/python" -m emerald.calibration "${calibration_args[@]}"
echo "Report: /var/lib/riri-emerald/calibration/latest.json"
echo "Calibration finished. Trading state and running services were not changed."
