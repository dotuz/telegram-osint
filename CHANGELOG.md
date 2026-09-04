# Changelog

## [0.13.0] - 2026-09-04 — Phase 13: Final QA, E2E, production readiness

Full-platform QA gate: real PostgreSQL 18 (migrate/downgrade/upgrade round-trip,
FK/unique/cascade verification, pg_dump/pg_restore drill), a genuine
Telegram-command → job → worker → OSINT → evidence → report → API E2E test, a
concurrency regression on refresh-token rotation, and a production Next.js
dashboard build/typecheck. See `PHASE_13_FINAL_QA_REPORT.md` for the full
evidence trail, test matrix, and findings.

### Fixed
- **Bot command flooding**: bot handlers had no rate limit, so an allow-listed
  user could flood the job queue / external OSINT sources. `apps/bot/guard.py`
  now enforces a per-Telegram-user, per-command sliding window
  (`RATE_LIMIT_BOT_PER_MINUTE`, default 20/min) before dispatching a handler.
- **Job queue silently broken on Redis outage**: `get_default_queue()` used
  `redis.from_url()`, which is lazy and never raises, so an unreachable Redis
  returned a `RedisJobQueue` that failed on first use instead of falling back
  to the in-memory queue. Added a connection probe (`RedisJobQueue.ping()`)
  mirroring the rate limiter's fallback pattern.
- **Orphaned jobs on enqueue failure**: `submit_job` committed the `Job` row
  before enqueueing; if `queue.enqueue()` raised, the row stayed `PENDING`
  forever with no worker able to see it. It's now transitioned to `FAILED`
  with a clear error before the exception propagates.
- **Refresh-token rotation race**: two concurrent `POST /auth/refresh` calls
  with the same token could both read it as active and each mint a valid
  successor. `RefreshTokenRepository.rotate()` now takes
  `SELECT ... FOR UPDATE` on the token row, so the second call serialises
  behind the first and lands in reuse detection (family revocation) instead.
- **Docker entrypoint not executable**: `docker/entrypoint.sh` was committed
  `100644`; `ENTRYPOINT` (exec form) requires the `+x` bit, so the production
  image would fail to start. Fixed the git mode (`100755`) and added a
  belt-and-suspenders `RUN chmod 0755` in `docker/Dockerfile`, applied before
  `USER appuser` so the write is unambiguous. Verified by running the fixed
  script directly (`sh entrypoint.sh migrate` / `api`) against a real
  PostgreSQL instance — migrations applied, `/health` and `/ready` both
  correct; the OCI image build/run itself remains untested (no Docker daemon
  in the CI/QA environment used for this phase).
- **Dashboard report download 401s**: the download links were bare
  `<a href="/api/v1/reports/{id}/download">` — a browser navigation sends no
  `Authorization` header and the refresh cookie is scoped to `/api/v1/auth`
  only, so every download 401'd once the dev shim was disabled. Replaced with
  `api.downloadReport()` — an authenticated `fetch` (refreshing once on 401)
  that saves the response as a blob.

### Added
- `tests/e2e/test_full_pipeline.py` — bot `/username` → job → worker (synthetic
  collector) → evidence → bot `/report` → job → report artifacts on disk → API
  retrieval of json/html/pdf → target graph → cross-user 404 isolation, all
  through the real handler/worker/API code paths.
- `tests/integration/test_queue_resilience.py`, `tests/security/test_bot_rate_limit.py`,
  `tests/security/test_refresh_concurrency.py` — regression coverage for the four
  fixes above.
- `tests/conftest.py` — opt-in `TOI_TEST_DATABASE_URL` so the whole suite can run
  against a real server database (used to validate PostgreSQL 18: 290/290 pass).
- `security/config.py` — `rate_limit_bot_per_minute` setting.
- `PHASE_13_FINAL_QA_REPORT.md` — full QA report: test matrix, findings with
  root cause/fix/regression test, PostgreSQL + backup/restore evidence, Docker
  and dashboard build status, threat-model reconciliation, GO decision.

### Verified (no code change needed)
- IDOR/BOLA, CSRF/Origin, CORS, SSRF guard, SQLi/XSS injection regression,
  rate limiting, secret non-exposure, refresh rotation/family-revocation — all
  re-run and green (`tests/security/`, 39 tests).
- PostgreSQL 18: `alembic upgrade head` / `downgrade base` / `upgrade head`
  round-trip, `alembic check` clean, FK/unique/cascade constraints enforced,
  290/290 tests pass against a live server database.
- Backup/restore: `pg_dump -Fc` → drop database → `pg_restore` → data and
  `alembic_version` intact.
- Dashboard: `npm install`, `tsc --noEmit`, `next build` (12/12 routes) all
  succeed; `next lint` clean.

## [0.12.0] - 2026-09-04 — Phase 12: Security hardening

### Added
- `security/ratelimit.py` — sliding-window rate limiter, Redis-backed
  (`zremrangebyscore`/`zadd`/`zcard` pipeline) with an in-memory fallback.
  `RATE_LIMIT_ENABLED` master switch (off in tests).
- `apps/api/security.py` — three HTTP defences:
  - `SecurityHeadersMiddleware` — `X-Content-Type-Options`, `X-Frame-Options: DENY`,
    `Referrer-Policy`, `Permissions-Policy`, `Cross-Origin-Opener-Policy`,
    CSP `default-src 'none'; frame-ancestors 'none'; …`, plus HSTS in production.
  - `OriginCheckMiddleware` — rejects a state-changing request whose `Origin` is
    present but not in `CORS_ALLOWED_ORIGINS` (403). No-Origin requests pass.
  - `rate_limit(bucket, …)` / `login_rate_limit` dependencies — per-principal
    quota + a wide per-IP backstop (`* RATE_LIMIT_IP_BURST_MULTIPLIER`), so a
    shared NAT never lets one user starve another. 429 + `Retry-After`.
- Rotating refresh tokens:
  - `database/models/refresh_token.py` + `database/repositories/refresh_tokens.py`
    (`issue` / `rotate` / `revoke` / `revoke_all`). Only the SHA-256 hash is
    stored; rotation is single-use; replaying a spent token revokes the whole
    family (`RefreshTokenReuseError`).
  - migration `0003_refresh_tokens`.
  - `POST /api/v1/auth/refresh` — reads the token from the body or the
    `toi_refresh` cookie (`HttpOnly; Secure; SameSite=Strict`, path
    `/api/v1/auth`). `login` now also sets that cookie; `logout` revokes it.
- `security/auth.py` — `new_refresh_token()` / `hash_refresh_token()`; token
  decode now maps `binascii.Error` to `TokenError` (malformed tokens → 401,
  never 500).
- `tests/security/` suite (32 tests): `test_idor_bola.py`, `test_auth_hardening.py`,
  `test_rate_limiting.py`, `test_headers_origin_csrf.py`, `test_refresh_rotation.py`,
  `test_injection.py`. 284 tests total.
- Settings: `RATE_LIMIT_ENABLED`, `RATE_LIMIT_API_PER_MINUTE`,
  `RATE_LIMIT_LOGIN_PER_MINUTE`, `RATE_LIMIT_IP_BURST_MULTIPLIER`,
  `ENFORCE_ORIGIN_CHECK`.

### Changed
- `apps/api/routers/jobs.py` — jobs are now scoped to their requester
  (`user:<id>` / `telegram:<id>`); non-owners get 404, admins see all.
- `apps/api/routers/{intel,username,reports}.py` — router-level rate-limit
  dependencies.
- Dashboard `lib/api.ts` — transparent refresh: a 401 on a non-auth path triggers
  one `POST /auth/refresh` (`credentials: "include"`) then a single retry.
- `RefreshToken.is_active` normalises SQLite's tz-naive round-trip before compare.

### Security
- Fixes the pre-Phase-12 gap where a job ID from another requester was readable.
- Malformed bearer tokens previously raised an unhandled `binascii.Error` (500);
  now a clean 401.

## [0.11.0] - 2026-09-04 — Phase 11: Web dashboard + auth

### Added — backend
- `security/auth.py` — stdlib-only auth: `scrypt` password hashing (salted,
  `scrypt$n$r$p$salt$hash`) + compact HMAC-SHA256-signed access tokens
  (`{sub, role, iat, exp}`).
- `apps/api/routers/auth.py` — `POST /api/v1/auth/login`, `GET /auth/me`,
  `POST /auth/logout`.
- `apps/api/deps.py` — `Principal` + `current_user` now resolves a
  `Authorization: Bearer` token first (role from the token is trusted); the
  `X-User-Email` shim is kept for dev/tests and **rejected when
  `APP_ENV=production`**. `require_admin` helper; `resolve_user` accepts a
  `Principal` / dict / email.
- `apps/api/routers/admin.py` — `GET /api/v1/stats` (per-user + graph + jobs
  counts) and `GET /api/v1/audit` (ADMIN only).
- `apps/api/cli.py` (`python -m apps.api create-user … [--admin]` /
  `set-password`).
- `UserRepository.create(password=…)` + `set_password`.
- 13 new tests (255 total): token/password roundtrip, expiry/tamper/malformed
  rejection, login + `/me`, bad-credential 401, token-scoped isolation,
  `/stats` vs `/audit` RBAC, dev-shim still works.

### Added — dashboard (`apps/dashboard/`)
- Next.js 14 App Router + TypeScript + Tailwind. Typed API client (`lib/api.ts`),
  auth context + route guard (`lib/auth.tsx`), sidebar nav (ADMIN sees Audit).
- Pages: overview (stats + source health), targets + target detail
  (overview / **SVG entity graph** / timeline tabs, "Generate report"), search
  (user / messages / username), watchlist (add / poll / unwatch), reports
  (generate + download json/html/pdf), jobs (auto-refresh + cancel), audit
  (admin), settings.
- `Dockerfile` (standalone build) + `docker-compose` `dashboard` service.

### Changed
- All API routers migrated from `user["email"]` to the `Principal` dependency.

## [0.10.0] - 2026-09-04 — Phase 10: Reports

### Added
- `reports/models.py` — `ReportContent` = the 15 spec sections in order, each a
  list of `Claim` (text + `FACT`/`INFERENCE`/`UNKNOWN` + `evidence_refs` +
  optional confidence) plus structured `data`.
- `reports/builder.py` — `ReportBuilder.build(report_id, target)`: assembles all
  15 sections from the graph / timeline / IOC / evidence layers, scoped to the
  target's resolved entities. Every material fact carries the ids of the
  `evidence` rows behind it; missing data is stated as `UNKNOWN`, never guessed.
- `reports/renderers/` — `render_json` (canonical), `render_html` (standalone,
  inline CSS, **every dynamic string HTML-escaped**), `render_pdf` (fpdf2, pure
  Python, `wrapmode="CHAR"` for long tokens; degrades if fpdf2 absent).
- `reports/service.py` — `generate_report(session, report_id, formats)`:
  build → render → write `REPORTS_DIR/<id>/report.{json,html,pdf}` → update the
  `Report` row (`content_json`, `artifacts_json`, `summary`, status).
- `workers/handlers.py::report_generate` — job handler; DMs a summary + download
  hint.
- Bot: `/report @username` (async job) and `/report list` live
  (`router.CURRENT_PHASE = 10`).
- API: `GET/POST /api/v1/reports`, `GET /api/v1/reports/{id}`,
  `GET /api/v1/reports/{id}/download?fmt=json|html|pdf` (FileResponse, falls back
  to stored content).
- `fpdf2` dependency; `REPORTS_DIR` setting (default `./reports_output`).
- 18 new tests (242 total): 15-section order, evidence-backed claims,
  UNKNOWN-not-guess, disclaimer language, HTML XSS-escaping, PDF magic bytes,
  service artifacts + row update + no-target failure, `report_generate` job +
  notification, bot `/report` (+list) + usage + denial, full API lifecycle +
  isolation.

## [0.9.0] - 2026-09-04 — Phase 9: Watchlist / monitoring

### Added
- `intelligence/monitoring.py` — `WatchMonitor.poll(entry)`: re-collects a
  watched handle's public presence (Telegram channel/group messages; optionally
  username-OSINT platform discovery), diffs against `last_seen_marker`
  (`{telegram_max_msg_id, platforms}`), emits one `Activity` per genuinely new
  public event, and advances the marker so the next poll doesn't re-notify.
  `due_watchlist_ids()` / `mark_scheduled()` for scheduling.
- `workers/scheduler.py` — `schedule_due_watches()`: finds active entries past
  the poll interval, enqueues one `watch_poll` job each, optimistically stamps
  `last_checked_at`. Wired into the worker loop as a periodic tick
  (`JobRunner(on_tick=…, tick_interval=…)`).
- `workers/handlers.py::watch_poll` — runs the monitor for one entry and delivers
  a `NEW PUBLIC ACTIVITY` notification to the watcher's DM (`user.telegram_user_id`);
  skips inactive entries.
- Bot: `/watch @username [sources]`, `/unwatch @username`, `/watchlist` live
  (`router.CURRENT_PHASE = 9`). `/watch` enforces
  `RATE_LIMIT_WATCH_MAX_TARGETS`, resolves a `Target`, and kicks an immediate
  first poll.
- API: `GET/POST /api/v1/watchlist`, `DELETE /api/v1/watchlist/{value}`,
  `POST /api/v1/watchlist/{id}/poll` (429 on limit).
- `WATCH_POLL_INTERVAL_SECONDS` setting (default 300).
- 15 new tests (224 total): monitor detection/dedupe/new-message/new-platform,
  due + mark-scheduled, scheduler no-double-enqueue, `watch_poll` job +
  notification + inactive-skip, bot `/watch` (+limit) `/unwatch` `/watchlist`,
  watchlist API + isolation.

### Fixed
- `WatchlistRepository.remove` returns `False` when the entry is already inactive.

## [0.8.0] - 2026-09-04 — Phase 8: Background workers

### Added
- `workers/queue.py` — `JobQueue` abstraction: `RedisJobQueue` (list + delayed
  sorted-set), `InMemoryJobQueue` (dev/tests); lazy process default with a
  Redis→memory fallback so dev without Redis still works.
- `workers/registry.py` — `@register(kind)` handler registry; `JobContext`
  (session + `progress()`), `JobOutcome` (`summary` + optional `Notification`).
- `workers/runner.py` — `JobRunner`: dequeue → `RUNNING` → dispatch → `COMPLETED`;
  on error `FAILED` then re-enqueued `PENDING` with exponential backoff up to
  `max_retries`; cancelled jobs skipped; per-progress-tick DB update; result
  notification delivered to the originating chat. Loop-safe (`_run_sync`) so it
  works from the worker (no loop) and from tests (pytest-asyncio loop).
- `workers/handlers.py` — job handlers for `telegram_user` / `telegram_group` /
  `telegram_channel` / `username_osint`, formatting results with the existing
  view functions; `set_collector_overrides` for offline tests.
- `workers/app.py` + `__main__.py` — `python -m workers`.
- `apps/bot/jobs.py` — `submit_job`, `cancel_job`, `find_job_id` (prefix lookup).
- Bot: `/search` `/user` `/group` `/channel` `/username` now **enqueue** and
  reply "queued"; the worker delivers the result. New `/cancel <job-id>`;
  admin `/jobs`, `/stats` live (`router.CURRENT_PHASE = 8`).
  `/message` and `/history` stay synchronous (DB-only).
- API: `GET /api/v1/jobs`, `GET /api/v1/jobs/{id}`, `POST /api/v1/jobs/{id}/cancel`.
- 20 new tests (209 total): queue FIFO/delay/timeout, runner lifecycle +
  retry/backoff + exhaustion + cancellation + loop-safety, handlers, bot
  enqueue→worker→notification round-trip, `/cancel`, jobs API.

### Changed
- Job state machine allows `PENDING → FAILED` (unhandleable kind fails fast).
- Existing bot handler tests updated for the async flow (`CapturingRunner`).

## [0.7.0] - 2026-09-04 — Phase 7: Entity resolution, graph, timeline

### Added
- `intelligence/entity_resolution/` — `TargetResolver` links a user's `Target`
  to the matching shared-graph entities (`TARGET_IS_ACCOUNT` /
  `TARGET_HAS_USERNAME`) with evidence, idempotently; `merge_entities()` repoints
  every relationship / message / evidence reference from a dropped entity onto
  the survivor (self-loops and duplicate edges collapsed).
- `database/models/evidence.py::allow_evidence_repointing()` — the one sanctioned
  evidence mutation (only `entity_id`/`entity_type`, only during a merge); the
  immutability guard now diffs changed attributes and rejects everything else.
- `intelligence/relationships/graph.py` — `GraphService`: bounded BFS
  neighbourhood (depth ≤ 3, node cap, edges pruned to the node set), node
  hydration with labels, `for_target()`.
- `intelligence/timeline/builder.py` — `TimelineService`: events from evidence
  (`observed_at`), messages (`posted_at`), relationships (`first_seen`), account
  first-observed; sorted, tz-normalised, grouped `by_year`.
- Search/username services now create + resolve a `Target` (`summary.target_id`
  / `result.target_id`).
- API: `GET/POST /api/v1/targets`, `GET /api/v1/targets/{id}`,
  `GET /api/v1/targets/{id}/{graph,timeline}`,
  `GET /api/v1/entities/{type}/{id}/{graph,timeline}`.
- Bot: `intel:timeline:<id>` / `intel:graph:<id>` callback (the buttons on a
  user-search result) rendered as text summaries with a dashboard pointer.
- 21 new tests (197 total): graph BFS/caps/hydration, timeline event kinds/
  ordering/year grouping, target resolution + idempotency, merge repointing +
  cross-type rejection + immutability-still-enforced, API, bot callbacks.

## [0.6.0] - 2026-09-04 — Phase 6: Username OSINT

### Added
- `collectors/common/http.py` — `SafeFetcher`: the single SSRF-guarded outbound
  HTTP choke point. Scheme allow-list; DNS resolved up front and every resolved
  address checked (loopback / private / link-local / ULA / multicast / reserved /
  cloud-metadata rejected); host re-validated after every redirect; redirect,
  size and timeout caps; injectable `transport` + `resolver` for offline tests;
  `HTTP_FETCH_ALLOW_PRIVATE` lab escape hatch.
- `collectors/username/` — adapter architecture: `UsernameAdapter` +
  `username_registry` (add a source = one file + `register()`). Built-ins:
  `GitHubAdapter`, `RedditAdapter`, `WebProbeAdapter` (+ `default_web_adapters`
  for x/instagram/youtube/tiktok/keybase/gitlab), `TelegramPresenceAdapter`.
  `UsernameOsintCollector` fans out concurrently, degrades per-adapter.
- `intelligence/confidence/` — correlation confidence engine (0–100). Weighted
  signals (username, display name, website domain, bio similarity, email, avatar,
  location); bands high/medium/low/username-only. **Never asserts identity** —
  strongest output is "high-confidence potential match"; `assert_safe_phrasing`
  guards output and is unit-tested.
- `intelligence/username_osint.py` — `UsernameOsintService`: runs the collector,
  persists `Username` + `ExternalAccount`/`TelegramAccount` entities, scores each
  account's corroboration with the others, records it as `identity_correlation`
  evidence, adds `USERNAME_FOUND_ON` + `ACCOUNT_POSSIBLY_SAME_AS` edges, always
  returns a disclaimer.
- Bot `/username <handle>` live (`router.CURRENT_PHASE = 6`); API
  `POST /api/v1/username`.
- `RelationshipType.ACCOUNT_POSSIBLY_SAME_AS` (no migration — `rel_type` is a
  free string column).
- 32 new tests (176 total): SSRF policy, confidence weights/bands/phrasing,
  adapters (MockTransport), collector fan-out + partial failure, service
  persistence/idempotency, bot, API.

### Fixed
- `security/logging.py` — logger factory now resolves `sys.stderr` at call time,
  so pytest's per-test capture never leaves a closed file handle behind
  (`cache_logger_on_first_use=False`).

## [0.5.0] - 2026-09-04 — Phase 5: IOC intelligence

### Added
- `intelligence/ioc/extract.py` — pure IOC extraction from public text: URLs,
  Telegram URLs, emails, IPv4/IPv6 (validated), domains, MD5/SHA1/SHA256
  (length-anchored), CVE, `@` handles. Re-fangs `hxxp` / `[.]` / `(dot)` /
  `[at]` first; resolves URL↔domain and email↔domain overlaps; drops filename
  "domains" (`report.pdf`); de-duplicates. Safe on untrusted content (data, not code).
- `intelligence/ioc/enrich.py` — `IocEnricher`: turns matches into `IOC` rows
  (+ typed `Domain`/`URL`/`IP` entities, `linked_entity_*` backfill), immutable
  `Evidence` referencing the source message, and `MESSAGE_CONTAINS_{IOC,DOMAIN,IP,
  URL}` / `MESSAGE_MENTIONS_USERNAME` edges. Also `enrich_entity_text` for
  bios/descriptions → `ACCOUNT_LINKED_TO_WEBSITE` / `DOMAIN_REFERENCED_BY_ACCOUNT`.
  Per-IOC failure is isolated; fully idempotent.
- `intelligence/ioc/service.py` — `IocService`: `for_message`, `for_container`
  (aggregates across a channel/group, resolves typed targets back to their IOC),
  `recent` with type filter.
- Wired into `IngestionService`: every stored public message is enriched
  automatically (`IngestSummary.iocs_extracted`).
- Surfacing: channel/group summaries carry `ioc_count`; message-search items
  carry `iocs`; bot message hits show an `IOC:` line; `GET /api/v1/iocs`
  (`?message_id` / `?entity_type&entity_id` / `?ioc_type` / recent).
- 24 new tests (144 total): extraction (types, defang, overlaps, negatives),
  enrichment (entities/edges/evidence, immutability, idempotency, bio links),
  service + API.

## [0.4.0] - 2026-09-04 — Phase 4: Public Telegram intelligence

### Added
- `collectors/common/` — `Collector` base class (`collect → normalize → validate
  → health_check`, orchestrated by `run()` which never raises), DTOs
  (`CollectRequest`, `RawBundle`, `NormalizedRecord`, `EvidenceDraft`,
  `RelationshipDraft`, `CollectResult`, `HealthStatus`), and `CollectorRegistry`.
- `collectors/telegram/` — swappable `TelegramSource` protocol
  (`Null`/`Fake`/`BotApi`/`Operator` sources; `build_source()` picks the best
  available) + `TelegramPublicCollector` for kinds `telegram_user`,
  `telegram_group`, `telegram_channel`, `telegram_message_search`. Extracts URLs
  and @mentions from message text. Honest about Bot API limits (empty + a note,
  never fabricated).
- `intelligence/ingest.py` — `IngestionService`: STORE step. Upserts entities via
  the deduplicating repositories, appends immutable evidence, observes graph
  edges; one bad record never sinks the batch.
- `intelligence/search.py` — `TelegramIntelService`: `search_user`, `group_intel`,
  `channel_intel`, `search_messages`, `history`. Creates per-user `Search` /
  `SearchResult` rows; degrades to the DB when the source is unavailable.
- Bot: `/search`, `/user`, `/group`, `/channel`, `/message`, `/history` are live
  (inline collection with a typing indicator; Phase 8 moves to jobs). `/help` no
  longer tags them "pending" (`router.CURRENT_PHASE = 4`).
- API: `POST /api/v1/telegram/{user,group,channel,messages}`, `GET
  /api/v1/searches`, `GET /api/v1/sources/health`. Dev-only `current_user` shim
  (`X-User-Email` header) until Phase 11/12 auth.
- 34 new tests (120 total): collector interface + Telegram collector, ingestion
  dedup/linking/partial-failure, intel service, bot handlers, API endpoints
  (incl. per-user isolation). Fully offline via `FakeTelegramSource`.

### Changed
- `apps/bot/auth.py` re-exports `Role` from `database.types` (single enum).
- Telegram entity dedup now resolves by `telegram_id` OR normalized username and
  backfills the missing key.

## [0.3.0] - 2026-09-04 — Phase 3: Database

### Added
- `database/types.py` — shared enums (`Role`, `SourceType`, `EntityType`,
  `RelationshipType`, `IOCType`, `TargetKind`, `SearchKind`, `TaskStatus`,
  `ReportFormat`, `Assertion`) stored as string values for PG/SQLite portability.
- `database/normalize.py` — canonicalisation for usernames (incl. `t.me/`),
  domains, URLs (+ sha256 hash), emails, IPs, CVEs, hashes.
- 18 domain models across `database/models/`:
  - identity: `User`
  - per-user (scoped to `user_id`): `Target`, `Search`, `SearchResult`,
    `Watchlist`, `Report`
  - shared graph: `TelegramAccount`, `TelegramGroup`, `TelegramChannel`,
    `Message`, `Username`, `ExternalAccount`, `Domain`, `URL`, `IP`, `IOC`,
    `Relationship`, `Evidence`
- Unique constraints on every entity to prevent duplicates; the §17 index set;
  `confidence` CHECK (0–100) on `evidence` and `relationship`.
- **Evidence immutability** enforced by a `before_flush` listener
  (`EvidenceImmutableError` on update/delete of a persisted row).
- Repository layer (`database/repositories/`): `BaseRepository._get_or_create`
  (savepoint-safe under a unique-constraint race); `UserRepository`;
  deduplicating `Username/ExternalAccount/Domain/URL/IP/IOC/TelegramAccount/
  TelegramGroup/TelegramChannel` repositories; append-only `EvidenceRepository`;
  observe-or-bump `RelationshipRepository`; `MessageRepository`;
  `ScopedRepository` + `Target/Search/Watchlist/Report` repositories (data-layer
  BOLA guard — cross-user ids resolve to `None`); `JobRepository` with a guarded
  state machine.
- Migration `0002_domain_schema` (autogenerated, `alembic check` clean, up/down
  round-trip verified on SQLite). Fixed doubled CHECK-constraint names in `0001`.
- 36 new tests: normalization, dedup, evidence immutability, relationship
  observe/bump, per-user scoping isolation, job state machine.

### Changed
- `database/base.py` — added `UUIDPrimaryKey` mixin.
- Alembic `post_write_hooks` disabled (ruff entrypoint lookup failed under venv);
  format new revisions with `ruff format database/migrations`.

## [0.2.0] - 2026-09-04 — Phase 2: Telegram bot

### Added
- `apps/bot/` — Telegram bot on `python-telegram-bot` v22:
  - `auth.py` — allow-list authorization; `ADMIN` / `ANALYST` roles;
    secure-by-default (empty allow-list denies everyone).
  - `router.py` — single command registry (name, summary, usage, admin flag,
    build phase, long-running flag); drives handler registration, the Telegram
    command menu, and `/help`.
  - `views.py` + `responses.py` + `keyboards.py` — pure, `telegram`-free view
    layer returning `BotMessage`; inline main menu per spec.
  - `guard.py` — `@authorized` decorator: denial → generic message + audit;
    handler exceptions → generic message + full log (never a stack trace).
  - `adapter.py` — the only send-path touching `telegram.*`; edits in place for
    callback queries.
  - `handlers/` — live: `/start`, `/help`, `/whoami`, `/admin`, `/health`,
    `menu:*` callbacks, unknown-command fallback; stub factory for
    not-yet-shipped commands.
  - `errors.py` — global error handler.
  - `app.py` — `build_application()` (import-safe, no network) + `run()` polling.
- `apps/bot/audit.py` — best-effort audit logging (never breaks a handler).
- `docs/BOT.md`.
- 28 new tests (unit + integration), fully offline (mock updates, no Telegram).

### Changed
- `AuditRepository.record` / bot audit accept `Mapping[str, object]` metadata.

## [0.1.0] - 2026-09-04 — Phase 1: Foundation

### Added
- Project scaffold: `apps/`, `workers/`, `collectors/`, `intelligence/`,
  `reports/`, `database/`, `security/`, `tests/`, `docker/`, `docs/`.
- `security/config.py` — typed `pydantic-settings` configuration, `SecretStr`
  secrets, wildcard-CORS rejection at load, production secret gate.
- `security/logging.py` — `structlog` logging, JSON in production,
  `request_id` / `job_id` bound via `contextvars`.
- `database/` — declarative `Base` with constraint naming convention,
  engine/session lifecycle (Postgres + SQLite), `Job` and `AuditLog` models,
  `AuditRepository` with secret scrubbing.
- Alembic wired to application settings; initial migration `0001_initial`
  (`job`, `audit_log`).
- `apps/api` — FastAPI app factory, request-context middleware, config-driven
  CORS, `/health` + `/ready` probes.
- Docker: multi-stage `Dockerfile`, role-dispatch `entrypoint.sh`,
  `docker-compose.yml` (db, redis, migrate, api, bot, worker).
- CI: GitHub Actions — ruff, ruff-format, mypy (non-blocking), migrations on
  Postgres, pytest + coverage, gitleaks, docker build.
- Tests: 22 tests across `unit/`, `integration/`, `security/` — fully offline.
- Docs: README, ARCHITECTURE, SECURITY, THREAT_MODEL, DATABASE, DEVELOPMENT,
  DEPLOYMENT, API, COLLECTORS.
