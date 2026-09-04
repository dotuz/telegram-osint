# Changelog

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
