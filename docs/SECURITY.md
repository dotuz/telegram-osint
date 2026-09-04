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

## AuthN / AuthZ (Phase 12)

- Dashboard: secure sessions; short-lived access tokens with refresh-token
  rotation if JWT is used; optional MFA.
- Bot: only numeric IDs in `TELEGRAM_ALLOWED_USER_IDS` may use commands; admin
  commands require `TELEGRAM_ADMIN_USER_IDS`.
- RBAC roles: `USER`, `ANALYST`, `ADMIN`. Authorization is always server-side;
  frontend-supplied roles are ignored.
- Every resource is scoped to the caller's workspace. Client-supplied IDs are
  never trusted → BOLA/IDOR protection with regression tests.

## Transport / browser controls (Phase 12)

- CORS: explicit allow-list only; `*` with credentials is rejected at config
  load. Tested against wildcard, null origin, malicious origin, preflight.
- CSRF: for cookie-authenticated browser flows — CSRF tokens, `SameSite`,
  `Secure`, `HttpOnly`, Origin/Referer checks on all state-changing endpoints.
  CORS is not treated as CSRF protection.

## SSRF protection (`collectors/common/http.py`, Phase 6)

All outbound OSINT HTTP goes through one class, `SafeFetcher`. Before every fetch
and again after **every** redirect: scheme allow-list (`http`/`https` only), DNS
resolved up front with **every** resolved address checked and rejected if
loopback / private / link-local / ULA / multicast / reserved / cloud-metadata
(`169.254.169.254`, `100.100.100.200`, `fd00:ec2::254`) / blocked hostname
(`metadata.google.internal`, `localhost`). Redirects capped, response size
capped (streamed, aborts mid-body), strict total timeout, every attempt logged.
`HTTP_FETCH_ALLOW_PRIVATE=true` is a lab-only escape hatch. Tested in
`tests/unit/test_ssrf_fetcher.py`; the Phase-12 suite adds the adversarial cases.

## Input validation

Pydantic schemas on every external input. Parameterised queries only — raw SQL
string concatenation is forbidden (enforced by review + `ruff` `S608`).
Protections: SQLi, command injection, path traversal, SSRF, XSS, template
injection, malicious filenames, oversized payloads.

## Rate limiting (Phase 12)

Per-user, per-IP, per-command, per-source. Configurable via
`RATE_LIMIT_*`. Reports are jobs/hour capped; watchlist has a max-targets cap.

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
