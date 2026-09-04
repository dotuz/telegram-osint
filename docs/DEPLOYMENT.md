# Deployment

## Image

One image, three roles. Build:

```bash
docker build -f docker/Dockerfile -t telegram-osint:<tag> .
```

`entrypoint.sh` dispatches on the command: `api`, `bot`, `worker`, `migrate`.
Runs as non-root `appuser` (uid 1001).

## Topology (production)

```
            ┌───────── nginx / reverse proxy (TLS, HSTS) ─────────┐
            │                                                     │
   dashboard (Next.js)                                      api (N replicas)
                                                                  │
                                     ┌────────────────────────────┼───────────┐
                                     │                            │           │
                               bot (1 replica)            worker (M replicas) │
                                     └──────────────┬─────────────┘           │
                                                    │                         │
                                       Redis (managed)        PostgreSQL (managed, backups on)
```

- Run the `migrate` role once per release **before** rolling `api`/`bot`/`worker`
  (init container or a pipeline step). The `api` role also self-migrates for
  single-node deployments only.
- `bot` must be a **single** replica for long polling (or use a webhook behind
  the proxy with a shared secret path).

## Configuration

All via environment / secret manager. Required in production:

| Var | Notes |
|-----|-------|
| `APP_ENV=production` | enables the secret gate, disables `/docs` |
| `APP_DEBUG=false` | enforced by the gate |
| `SECRET_KEY` | 64-byte urlsafe; rotate with refresh-token invalidation |
| `TELEGRAM_BOT_TOKEN` | from @BotFather |
| `TELEGRAM_ALLOWED_USER_IDS` / `TELEGRAM_ADMIN_USER_IDS` | comma-separated numeric IDs |
| `DATABASE_URL` | `postgresql+psycopg://...`; least-privilege DB user |
| `REDIS_URL` | managed Redis; separate DB index from dev |
| `CORS_ALLOWED_ORIGINS` | explicit dashboard origin(s); never `*` |

`Settings.require_production_secrets()` aborts startup if these are missing or
misconfigured.

## Reverse proxy

Terminate TLS; set `Strict-Transport-Security`, `X-Content-Type-Options`,
`X-Frame-Options: DENY`, and a CSP for the dashboard. Forward `X-Request-ID`.
Cap request body size. Rate-limit at the edge in addition to app-level limits.

## Health & readiness

- Liveness: `GET /health` (no dependency checks).
- Readiness: `GET /ready` (503 until DB + Redis reachable). Wire to the
  orchestrator's readiness probe and the compose healthcheck.

## Backups / DR

- Postgres: automated daily snapshots + PITR; test restore quarterly (Phase 13
  backup/restore test).
- Redis is a cache/queue — treat as ephemeral; jobs are re-drivable.

## Observability

Structured JSON logs (`LOG_JSON=true`) shipped to your aggregator; every line
carries `request_id`/`job_id`. Track API latency, failed jobs, collector
failures, DB/Redis health, queue length (Phase 30).
