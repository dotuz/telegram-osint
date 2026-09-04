# Dashboard

Next.js 14 (App Router) + TypeScript + Tailwind. Talks to the platform API via
the `/api/*` rewrite (`API_INTERNAL_URL`, default `http://localhost:8000`).

## Develop

```bash
cd apps/dashboard
npm install
# API must be running on :8000 (make run-api) and have a user:
#   python -m apps.api create-user you@example.com --admin
npm run dev            # http://localhost:3000
```

## Build / Docker

```bash
npm run build && npm start
# or
docker build -t telegram-osint-dashboard .
```

## Auth

Login (`/login`) posts to `POST /api/v1/auth/login`; the access token is kept in
`localStorage` and sent as `Authorization: Bearer …`. `useRequireAuth()` guards
every page under `app/(app)/`. The `Audit` nav item shows only for `ADMIN`.

## Pages

`/` overview · `/targets` + `/targets/[id]` (overview / graph / timeline) ·
`/search` · `/watchlist` · `/reports` · `/jobs` (auto-refresh) · `/audit` (admin) ·
`/settings`.

The graph view is a dependency-free SVG (deterministic circular layout) — enough
to read the shape; a physics layout can be swapped in later.
