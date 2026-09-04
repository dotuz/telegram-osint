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

## Phase 4 surface (`/api/v1`)

Auth is a **dev shim** until Phase 11/12: the caller is identified by the
`X-User-Email` header (default `analyst@local`); a user row is created on first
use and every search/result is scoped to it.

| Method | Path | Body | Returns |
|--------|------|------|---------|
| POST | `/api/v1/telegram/user` | `{query}` | `IntelResponse` (public profile summary + evidence count) |
| POST | `/api/v1/telegram/group` | `{query}` | `IntelResponse` |
| POST | `/api/v1/telegram/channel` | `{query}` | `IntelResponse` |
| POST | `/api/v1/telegram/messages` | `{query, limit}` | `IntelResponse` with `items[]` |
| GET | `/api/v1/searches` | — | `{searches: [...]}` (this user's history) |
| GET | `/api/v1/sources/health` | — | `{sources: [{name, healthy, detail}]}` |
| GET | `/api/v1/iocs` | `?message_id` \| `?entity_type&entity_id` \| `?ioc_type` \| (recent) | `{iocs: [{id, ioc_type, value, times_observed, linked_entity_*, evidence_count}]}` |
| POST | `/api/v1/username` | `{username}` | `{username, found, sources: [{platform, url, confidence, evidence[]}], same_as_edges, notes, disclaimer}` — `confidence` is correlation (0–100); every response carries a "not proof of a shared identity" disclaimer |
| GET · POST | `/api/v1/targets` | POST `{kind, value, label?}` | list / create + resolve a target (scoped to the caller) |
| GET | `/api/v1/targets/{id}` | — | `{id, kind, value, label, resolved_entities[]}` |
| GET | `/api/v1/targets/{id}/graph` | `?depth=1..3` | `{root, nodes[], edges[], truncated}` |
| GET | `/api/v1/targets/{id}/timeline` | — | `{root, events[], by_year, truncated}` |
| GET | `/api/v1/entities/{type}/{id}/graph` | `?depth=1..3` | shared-graph neighbourhood |
| GET | `/api/v1/entities/{type}/{id}/timeline` | — | chronological events for one entity |
| GET | `/api/v1/jobs` | `?limit` | recent background jobs |
| GET | `/api/v1/jobs/{id}` | — | job detail (state, progress, params, result, timestamps) |
| POST | `/api/v1/jobs/{id}/cancel` | — | `{cancelled: bool, state}` |
| GET · POST | `/api/v1/watchlist` | POST `{value, sources?}` | list / add (`429` on `RATE_LIMIT_WATCH_MAX_TARGETS`) |
| DELETE | `/api/v1/watchlist/{value}` | — | `{removed: bool}` |
| POST | `/api/v1/watchlist/{id}/poll` | — | run a poll now → `{target, activities[], notes}` |

`IntelResponse`: `{kind, found, entity_type, entity_id, summary, items, notes,
search_id, source_available}`. When no Telegram source is configured,
`source_available=false` and results come only from the collected corpus.

## Planned surface

| Phase | Endpoints (sketch) |
|------:|--------------------|
| 11 | `POST /auth/login`, `POST /auth/refresh`, `POST /auth/logout` |
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
