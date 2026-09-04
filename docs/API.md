# HTTP API

Base URL: `http://<host>:8000`. Interactive docs at `/docs` (non-production only).
Every response carries `X-Request-ID` (echoed from the request if supplied).

## Phase 1 surface

### `GET /health`

Liveness. No auth, no dependency checks.

```json
{ "status": "ok", "env": "development", "version": "0.1.0" }
```

### `GET /ready`

Readiness. Checks database + Redis. `200` when all healthy, `503` otherwise.

```json
{ "ready": false, "checks": { "database": "ok", "redis": "error" } }
```

## Planned surface

| Phase | Endpoints (sketch) |
|------:|--------------------|
| 11 | `POST /auth/login`, `POST /auth/refresh`, `POST /auth/logout` |
| 4 | `POST /search`, `GET /targets`, `GET /targets/{id}`, `GET /messages` |
| 6 | `POST /username-osint`, `GET /sources`, `GET /sources/health` |
| 7 | `GET /targets/{id}/graph`, `GET /targets/{id}/timeline` |
| 8 | `GET /jobs`, `GET /jobs/{id}`, `POST /jobs/{id}/cancel` |
| 9 | `GET/POST/DELETE /watchlist` |
| 10 | `POST /reports`, `GET /reports/{id}`, `GET /reports/{id}/download?fmt=pdf|html|json` |
| 29 | `GET /admin/...` (RBAC: ADMIN) |

## Conventions (from Phase 12)

- Auth: `Authorization: Bearer <access-token>`; refresh-token rotation.
- All state-changing requests from browsers require `X-CSRF-Token` + Origin check.
- Resource IDs are authorized against the caller's workspace — never trusted blindly.
- Pagination: `?limit=&cursor=`. Rate-limit headers: `X-RateLimit-*`.
- Errors: `{ "error": { "code": "...", "message": "..." } }` — no stack traces.
