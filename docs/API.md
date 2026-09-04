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

## Authentication

- `POST /api/v1/auth/login` `{email, password}` →
  `{access_token, token_type, expires_in, refresh_token, user}`. Also sets a
  `toi_refresh` cookie (`HttpOnly; Secure; SameSite=Strict`, path
  `/api/v1/auth`). Rate-limited per IP (`RATE_LIMIT_LOGIN_PER_MINUTE`).
- Send the access token as `Authorization: Bearer <token>` on every request.
  `GET /api/v1/auth/me` returns the current user. Tokens are HMAC-signed,
  short-lived (`ACCESS_TOKEN_TTL_SECONDS`). A malformed token → `401`.
- `POST /api/v1/auth/refresh` — body `{refresh_token?}` or the `toi_refresh`
  cookie → a fresh `{access_token, refresh_token}` and rotates the cookie.
  **Single-use**: the old token is revoked. Replaying a spent token → `401` and
  revokes every refresh token for that user (theft response).
- `POST /api/v1/auth/logout` — revokes the presented refresh token and clears
  the cookie.
- Create users with `python -m apps.api create-user <email> [--admin]`.
- **Dev shim** (kept for local dev + the test suite, **401 in production**):
  `X-User-Email` identifies/creates a user; `X-User-Role: ADMIN` elevates.
- `GET /api/v1/stats` — dashboard counts. `GET /api/v1/audit` — audit log (ADMIN).

### Rate limiting & 429

Search, username, and report endpoints are rate-limited per authenticated
principal (with a wider per-IP backstop). Over the limit → `429 Too Many
Requests` with `Retry-After` and `X-RateLimit-Limit` headers. Disable entirely
with `RATE_LIMIT_ENABLED=false`.

### Browser / CSRF

State-changing requests (`POST/PUT/PATCH/DELETE`) carrying an `Origin` header not
in `CORS_ALLOWED_ORIGINS` are rejected with `403` (`ENFORCE_ORIGIN_CHECK`).
Responses carry `X-Frame-Options: DENY`, `X-Content-Type-Options: nosniff`, and a
strict CSP.

Every target / search / watchlist / report is scoped to the resolved user.

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
| GET · POST | `/api/v1/reports` | POST `{value \| target_id, formats?}` | list / create + generate (15 sections, evidence-linked) |
| GET | `/api/v1/reports/{id}` | — | status + parsed `content` |
| GET | `/api/v1/reports/{id}/download` | `?fmt=json\|html\|pdf` | artifact file (or stored content fallback) |

`IntelResponse`: `{kind, found, entity_type, entity_id, summary, items, notes,
search_id, source_available}`. When no Telegram source is configured,
`source_available=false` and results come only from the collected corpus.

## Surface by phase (all shipped)

| Phase | Endpoints |
|------:|-----------|
| 1 | `GET /health`, `GET /ready` |
| 4 | `POST /api/v1/telegram/{user,group,channel,messages}`, `GET /api/v1/searches`, `GET /api/v1/sources/health` |
| 5 | `GET /api/v1/iocs` |
| 6 | `POST /api/v1/username` |
| 7 | `GET/POST /api/v1/targets`, `GET /api/v1/targets/{id}`, `GET /api/v1/targets/{id}/{graph,timeline}`, `GET /api/v1/entities/{type}/{id}/{graph,timeline}` |
| 8 | `GET /api/v1/jobs`, `GET /api/v1/jobs/{id}`, `POST /api/v1/jobs/{id}/cancel` |
| 9 | `GET/POST /api/v1/watchlist`, `DELETE /api/v1/watchlist/{value}`, `POST /api/v1/watchlist/{id}/poll` |
| 10 | `GET/POST /api/v1/reports`, `GET /api/v1/reports/{id}`, `GET /api/v1/reports/{id}/download?fmt=json\|html\|pdf` |
| 11 | `GET /api/v1/stats`, `GET /api/v1/audit` (ADMIN) |
| 12 | `POST /api/v1/auth/{login,refresh,logout}`, `GET /api/v1/auth/me` |

## Conventions

- Auth: `Authorization: Bearer <access-token>` on every call; `POST /auth/refresh`
  rotates it (see **Authentication**). A malformed token → 401.
- State-changing requests (`POST/PUT/PATCH/DELETE`) with a foreign `Origin`
  header → 403 (`ENFORCE_ORIGIN_CHECK`). The refresh cookie is `SameSite=Strict`.
- Resource IDs are authorized against the caller's per-user data — never trusted
  blindly. The shared intelligence graph (`/iocs`, `/entities/*`) is visible to
  every authenticated analyst by design.
- Rate limits: 429 with `Retry-After` + `X-RateLimit-Limit` on search / username
  / report endpoints; disable with `RATE_LIMIT_ENABLED=false`.
- Errors: FastAPI's `{ "detail": ... }` — generic messages, no stack traces.
- Every response carries `X-Request-ID` (echoed from the request or generated).
