#!/usr/bin/env bash
set -euo pipefail

if [[ "${EUID}" -ne 0 ]]; then
  echo "Run this script as root." >&2
  exit 1
fi

project_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"

if [[ "${project_root}" == "/opt/riri" || "${project_root}" == /opt/riri-releases/* ]]; then
  echo "Refusing to install EMERALD from an existing RIRI path." >&2
  exit 1
fi

if ! id riri-emerald >/dev/null 2>&1; then
  useradd --system --home /var/lib/riri-emerald --shell /usr/sbin/nologin riri-emerald
fi

install -d -o root -g root -m 0755 /opt/riri-emerald /opt/riri-emerald/releases
install -d -o riri-emerald -g riri-emerald -m 0700 /var/lib/riri-emerald
install -d -o root -g riri-emerald -m 0750 /etc/riri-emerald

if [[ ! -f /etc/riri-emerald/emerald.env ]]; then
  install -o root -g riri-emerald -m 0640 \
    "${project_root}/.env.production.example" /etc/riri-emerald/emerald.env
  echo "Created /etc/riri-emerald/emerald.env. Replace placeholder token before starting."
fi

install -o root -g root -m 0644 \
  "${project_root}/infra/systemd/riri-emerald-api.service" \
  /etc/systemd/system/riri-emerald-api.service
install -o root -g root -m 0644 \
  "${project_root}/infra/nginx/api-emerald.albiagent.com.conf" \
  /etc/nginx/sites-available/api-emerald.albiagent.com.conf
ln -sfn /etc/nginx/sites-available/api-emerald.albiagent.com.conf \
  /etc/nginx/sites-enabled/api-emerald.albiagent.com.conf

systemctl daemon-reload
nginx -t

echo "EMERALD namespace bootstrapped. Existing RIRI services and paths were not modified."
echo "Next: configure /etc/riri-emerald/emerald.env, then run deploy-emerald.sh."
