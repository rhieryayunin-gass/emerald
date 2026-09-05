# EMERALD Production-Style Demo Deployment

This deployment is isolated from the existing RIRI application at every
identity and filesystem boundary.

## Targets

- Repository: a dedicated `riri-emerald` repository.
- Dashboard: new Vercel project `riri-emerald-dashboard` with custom domain
  `emerald.albiagent.com`.
- API: `api-emerald.albiagent.com` through a separate NGINX virtual host.
- Internal API bind: `127.0.0.1:8010`.
- System service: `riri-emerald-api.service`.
- Releases: `/opt/riri-emerald/releases`.
- Persistent state: `/var/lib/riri-emerald/emerald.db`.
- Environment file: `/etc/riri-emerald/emerald.env`.

Nothing in the supplied scripts writes to `/opt/riri`, `/opt/riri-releases`, the
`riri-api` unit, or the `api-riri.albiagent.com` NGINX configuration.

## Backend sequence

1. Place a checkout of the dedicated repository outside existing RIRI paths.
2. Install `uv`, `rsync`, NGINX, and curl on the VPS.
3. Run `sudo infra/vps/bootstrap-emerald.sh` once.
4. Generate a dedicated token with `openssl rand -hex 32` and put it only in
   `/etc/riri-emerald/emerald.env` as `EMERALD_API_TOKEN`.
5. Run `sudo infra/vps/deploy-emerald.sh`.
6. Point DNS for `api-emerald.albiagent.com` to the VPS and provision HTTPS for
   that hostname. Keep `api-riri.albiagent.com` unchanged.
7. Verify both `https://api-emerald.albiagent.com/health` and the existing RIRI
   health endpoint independently.

Only one Uvicorn worker is configured because the current live tick buffer is
in memory. Horizontal workers require moving that buffer to a shared event
store first.

## Frontend sequence

Follow `infra/vercel/README.md`. The backend token and dashboard secrets must be
Vercel server environment variables and must never use a `NEXT_PUBLIC_` prefix.

## MT5 sequence

Compile and install `apps/mt5/RIRI_EMERALD_DEMO_v1_202.mq5`, allow only the
dedicated HTTPS API URL, and keep AutoTrading disabled during the first telemetry
verification. Entry remains technically unavailable while
`EMERALD_PROBABILITY_MODEL_READY=false`.
