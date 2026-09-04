# Security

## Purpose and boundary

This is an **OSINT / intelligence** platform. Its power comes from correlation,
evidence, search, entity resolution, timelines, graph analysis, confidence
scoring, monitoring, automation, and reporting — **not** from unauthorized
access.

### Never implemented (hard limit)

- Telegram session stealing / session-string extraction from any device
- Malware delivery; credential / password harvesting
- OTP / 2FA interception; auth-token or cookie theft
- Account takeover
- Private-chat / private-group scraping without explicit authorization
- Extracting credentials or secrets from user devices
- Infecting or attacking the bot's own users
- Collecting information Telegram does not legitimately expose

The `/start` interaction (and every other interaction) **must never** attempt to
obtain Telegram sessions, tokens, passwords, OTP codes, cookies, or device
credentials. If a feature request would require any of the above, it is rejected.

### Permitted data sources

1. Telegram **Bot API** data legitimately delivered to the bot.
2. Publicly accessible Telegram content.
3. Public OSINT sources (GitHub, Reddit, public web, ...).
4. An explicitly authorized operator account (Telethon/Pyrogram) **only** where
   the operator has legally configured one via `TELEGRAM_OPERATOR_*`.

Unavailable data is reported as `UNKNOWN`. The platform never fabricates IDs,
usernames, memberships, messages, relationships, or timestamps.

## Secrets management

- All secrets come from environment variables (or a secret manager in prod).
  Nothing secret is committed; `.env` is git-ignored, `.env.example` is the
  template.
- Secrets are typed as `pydantic.SecretStr` — they render as `**********` in
  logs, `repr()`, and error messages. Tests assert this.
- `Settings.require_production_secrets()` refuses to start a production process
  with an empty `SECRET_KEY` / `TELEGRAM_BOT_TOKEN`, with `APP_DEBUG=true`, or
  with wildcard CORS.
- Frontend never receives secrets; the dashboard talks only to the API.
- CI runs `gitleaks` on every push/PR.

## AuthN / AuthZ

- **Dashboard / API**: `scrypt` password hashes (salted); login issues a
  short-lived HMAC-SHA256-signed access token carrying `{sub, role, exp}`.
  Role in the token is trusted; the `X-User-Email`/`X-User-Role` dev shim is
  **refused when `APP_ENV=production`** (`test_auth_hardening.py`). Malformed
  tokens return 401, never 500.
- **Refresh-token rotation (Phase 12)**: login also issues a rotating refresh
  token — delivered as an `HttpOnly; Secure; SameSite=Strict` cookie scoped to
  `/api/v1/auth` and in the body for non-browser clients. Only its SHA-256 hash
  is stored. `POST /api/v1/auth/refresh` is single-use: it revokes the presented
  token and issues a new one. Presenting an already-spent token is treated as
  theft and revokes the **entire** token family for that user. `logout` revokes.
  `rotate()` takes `SELECT ... FOR UPDATE` on the token row (Phase 13) so two
  concurrent refresh calls with the same token cannot both mint a valid
  successor — the second serialises behind the first and lands in reuse
  detection. Tested in `test_refresh_rotation.py`, `test_refresh_concurrency.py`.
- The dashboard keeps the **access token** in `localStorage` (short TTL, never
  the refresh token) and the **refresh token** only in the HttpOnly cookie —
  JavaScript, including an XSS payload, can read the access token but not the
  refresh token, bounding the blast radius to the access-token TTL.
- **Bot**: only numeric IDs in `TELEGRAM_ALLOWED_USER_IDS` may use commands;
  admin commands require `TELEGRAM_ADMIN_USER_IDS`.
- **RBAC** roles: `USER`, `ANALYST`, `ADMIN`. Authorization is always
  server-side (`require_admin` on `/audit`, admin-only bot commands); a
  frontend-supplied role is only honoured through the dev shim, never in prod.
- Every resource is scoped to the caller's resolved user. Client-supplied IDs
  are never trusted → BOLA/IDOR protection with regression tests
  (`test_api_auth_admin.py::test_token_auth_scopes_data_to_the_token_user`,
  `tests/security/test_idor_bola.py`). Background jobs are scoped to their
  requester (`user:<id>` / `telegram:<id>`); a non-owner gets 404, an admin sees
  all.

## Transport / browser controls (Phase 12)

- **Security headers** (`SecurityHeadersMiddleware`): `X-Content-Type-Options:
  nosniff`, `X-Frame-Options: DENY`, `Referrer-Policy`, `Permissions-Policy`,
  `Cross-Origin-Opener-Policy: same-origin`, CSP `default-src 'none';
  frame-ancestors 'none'; …`, and HSTS in production.
- **CORS**: explicit allow-list only; `*` with credentials is rejected at config
  load. Tested against wildcard, null origin, malicious origin, preflight.
- **CSRF / Origin check** (`OriginCheckMiddleware`): every state-changing verb
  (`POST/PUT/PATCH/DELETE`) whose `Origin` header is present but not in
  `CORS_ALLOWED_ORIGINS` is rejected with 403. Requests with no `Origin`
  (server-to-server, curl) pass — token auth already binds them. Combined with
  the `SameSite=Strict` refresh cookie this covers the browser cookie flow.
  CORS is not treated as CSRF protection. Tested in
  `test_headers_origin_csrf.py`. Toggle: `ENFORCE_ORIGIN_CHECK`.

## SSRF protection (`collectors/common/http.py`, Phase 6)

All outbound OSINT HTTP goes through one class, `SafeFetcher`. Before every fetch
and again after **every** redirect: scheme allow-list (`http`/`https` only), DNS
resolved up front with **every** resolved address checked and rejected if
loopback / private / link-local / ULA / multicast / reserved / cloud-metadata
(`169.254.169.254`, `100.100.100.200`, `fd00:ec2::254`) / blocked hostname
(`metadata.google.internal`, `localhost`). Redirects capped, response size
capped (streamed, aborts mid-body), strict total timeout, every attempt logged.
`HTTP_FETCH_ALLOW_PRIVATE=true` is a lab-only escape hatch. Tested in
`tests/unit/test_ssrf_fetcher.py`.

## Input validation

Pydantic schemas on every external input. Parameterised queries only — raw SQL
string concatenation is forbidden (enforced by review + `ruff` `S608`).
Protections: SQLi, command injection, path traversal, SSRF, XSS, template
injection, malicious filenames, oversized payloads.

## Rate limiting (Phase 12, extended Phase 13)

`security/ratelimit.py` — a sliding-window limiter, Redis-backed
(`zremrangebyscore`/`zadd`/`zcard` pipeline) with an in-memory fallback, same
pattern as the job queue. Each guarded API endpoint enforces two keys: a
**per-principal** quota (the real limit, keyed on `user_id`/email so a spoofed
`X-Forwarded-For` or a shared NAT cannot lift it) and a much wider **per-IP**
backstop (`limit * RATE_LIMIT_IP_BURST_MULTIPLIER`). Login is limited per-IP
only (no principal yet). Over-limit → `429` with `Retry-After` /
`X-RateLimit-*`. Master switch `RATE_LIMIT_ENABLED` (off in the test suite);
limits configurable via `RATE_LIMIT_*`. Reports are jobs/hour capped; watchlist
has a max-targets cap. Tested in `tests/security/test_rate_limiting.py`.

The **bot** enforces the same limiter per Telegram user id + command
(`apps/bot/guard.py`, `RATE_LIMIT_BOT_PER_MINUTE`, default 20/min) — closed in
Phase 13 after final QA found an allow-listed user could otherwise flood the
job queue / external OSINT sources with unthrottled `/search`, `/username`,
`/report` calls. Tested in `tests/security/test_bot_rate_limit.py`.

Reverse-proxy deployments must run uvicorn with `--proxy-headers` and a
trusted-hosts allow-list (or terminate TLS at a proxy that sets the real client
IP correctly) — the rate limiter and audit log use `request.client.host`
as-is and never trust `X-Forwarded-For` from an untrusted hop.

## Audit logging

`database/models/audit_log.py` — append-only. Logs login/logout, search, target/
report/watchlist changes, API-key changes, admin actions, failed auth, permission
denied, collector errors. `AuditRepository` scrubs forbidden keys (`password`,
`token`, `otp`, `cookie`, `session`, ...) before persisting metadata. Passwords,
tokens, OTPs, cookies, and secrets are never logged.

## AI / NLP layer

AI never replaces evidence collection and never invents evidence. Pipeline:
`COLLECT → NORMALIZE → VALIDATE → STORE → CORRELATE → AI ANALYSIS → REPORT`.
Every AI claim references underlying evidence and is labelled `FACT`,
`INFERENCE`, or `UNKNOWN`. Untrusted collected content is treated as data, never
as instructions (prompt-injection mitigation).

## Error handling

Telegram users never see stack traces — they get e.g. `Collection failed. Source
unavailable.` Full diagnostics go to structured logs. One failing source never
discards successful results from others.

## Reporting a vulnerability

Email the operator. Do not open public issues for security reports.
