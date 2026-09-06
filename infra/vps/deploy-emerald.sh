#!/usr/bin/env bash
set -euo pipefail

if [[ "${EUID}" -ne 0 ]]; then
  echo "Run this script as root." >&2
  exit 1
fi

project_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
release_id="$(date -u +%Y%m%dT%H%M%SZ)"
release_dir="/opt/riri-emerald/releases/${release_id}"

if [[ ! -f /etc/riri-emerald/emerald.env ]]; then
  echo "Missing /etc/riri-emerald/emerald.env. Run bootstrap-emerald.sh first." >&2
  exit 1
fi
if grep -q 'replace-with-' /etc/riri-emerald/emerald.env; then
  echo "Refusing deployment while placeholder secrets remain in emerald.env." >&2
  exit 1
fi
if ! grep -qx 'EMERALD_ENVIRONMENT=demo' /etc/riri-emerald/emerald.env ||
   ! grep -qx 'EMERALD_ALLOW_REAL_TRADING=false' /etc/riri-emerald/emerald.env ||
   ! grep -qx 'EMERALD_PROBABILITY_MODEL_READY=false' /etc/riri-emerald/emerald.env; then
  echo "Refusing deployment unless demo, real-trading lock, and model lock are explicit." >&2
  exit 1
fi
if [[ "${project_root}" == "/opt/riri" || "${project_root}" == /opt/riri-releases/* ]]; then
  echo "Refusing to deploy EMERALD from an existing RIRI path." >&2
  exit 1
fi

install -d -o root -g root -m 0755 "${release_dir}"
rsync -a --delete \
  --exclude '.git/' \
  --exclude '.env' \
  --exclude '.venv/' \
  --exclude 'data/' \
  --exclude 'apps/dashboard/node_modules/' \
  --exclude 'apps/dashboard/.next/' \
  "${project_root}/" "${release_dir}/"

cd "${release_dir}"
uv sync --frozen --no-dev
chown -R root:root "${release_dir}"
ln -sfn "${release_dir}" /opt/riri-emerald/current.new
mv -Tf /opt/riri-emerald/current.new /opt/riri-emerald/current

systemctl enable --now riri-emerald-api.service
systemctl restart riri-emerald-api.service
nginx -t
systemctl reload nginx

for attempt in {1..20}; do
  if curl -fsS -H 'Host: api-emerald.albiagent.com' http://127.0.0.1:8010/health | \
     grep -q '"environment":"demo"'; then
    echo "RIRI_EMERALD_READY release=${release_id}"
    exit 0
  fi
  sleep 1
done

echo "EMERALD health check failed. Inspect: journalctl -u riri-emerald-api -n 100" >&2
exit 1
