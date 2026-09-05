# Separate Vercel Project

Create a new Vercel project named `riri-emerald-dashboard`. Do not import the
existing RIRI frontend project and do not assign `albiagent.com` to this project.

Configuration:

- Root directory: `apps/dashboard`
- Production domain: `emerald.albiagent.com`
- Framework: Next.js
- Region: Singapore (`sin1`)
- Environment variables:
  - `EMERALD_API_BASE_URL=https://api-emerald.albiagent.com`
  - `EMERALD_API_TOKEN` (same dedicated EMERALD API token stored on the VPS)
  - `EMERALD_DASHBOARD_PASSWORD` (at least 12 characters)
  - `EMERALD_SESSION_SECRET` (at least 32 random characters)

All four values are server-only. Never prefix them with `NEXT_PUBLIC_`.
