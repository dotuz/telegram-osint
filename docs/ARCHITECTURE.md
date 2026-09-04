# Architecture

## Style

**Modular monolith** with enforced module boundaries. One deployable backend
image runs in three roles (`api`, `bot`, `worker`) selected by the container
command. Modules communicate through typed interfaces and the database, never by
reaching into each other's internals, so any module can later be extracted into
its own service.

## Data flow

```
Telegram User
    │  (Bot API updates: commands, callback queries — bot-scoped data only)
    ▼
apps/bot ──────────────► apps/api  (Application layer: use-cases, validation)
                              │
                 ┌────────────┴────────────┐
                 ▼                         ▼
        security (authn/authz)      Job Queue (Redis)
                                           │
                                           ▼
                                     workers/  (consume jobs)
                                           │
              ┌────────────────────────────┼────────────────────────────┐
              ▼                            ▼                            ▼
   collectors/telegram          collectors/{username,github,     intelligence/
   (public TG content)           reddit,web}  (public OSINT)      (correlate, score)
              └────────────────────────────┼────────────────────────────┘
                                           ▼
                          normalize → validate → Evidence + entities
                                           ▼
                                      database (PostgreSQL)
                                           │
              ┌────────────────────────────┼────────────────────────────┐
              ▼                            ▼                            ▼
        Search (PG FTS)            intelligence graph/timeline      reports/ (PDF/HTML/JSON)
                                           ▼
                                    apps/dashboard (Next.js)
```

## Module boundaries

| Module | Depends on | Must **not** depend on |
|--------|-----------|------------------------|
| `apps/bot` | `apps/api` app-services, `security` | collectors, intelligence internals |
| `apps/api` | `database.repositories`, `security`, job-queue client | collector implementations |
| `workers` | `collectors`, `intelligence`, `database` | `apps/bot`, `apps/api` handlers |
| `collectors/*` | `collectors/common` | `intelligence`, `database.models` (return DTOs) |
| `intelligence/*` | `database` (read/write via repositories) | `collectors/*` |
| `reports` | `database.repositories`, `intelligence` read models | collectors |
| `database` | — | everything else |
| `security` | `database` (for auth/audit) | `apps/*` handlers |

Collectors return **plain DTOs + evidence**; the worker persists them. This keeps
each collector independent of the schema and of the intelligence engine.

## Collector interface

Every collector implements (`collectors/common`):

```python
class Collector(Protocol):
    name: str

    async def collect(self, request: CollectRequest) -> CollectResult: ...
    def normalize(self, raw: RawRecords) -> list[NormalizedRecord]: ...
    def validate(self, records: list[NormalizedRecord]) -> list[NormalizedRecord]: ...
    async def health_check(self) -> HealthStatus: ...
```

## Application-layer contract

- Telegram handlers and HTTP handlers **never** run long collection inline. They
  validate input, enqueue a `Job`, and return immediately with a job id.
- Every read is scoped to the authenticated principal's workspace. IDs supplied
  by clients are never trusted for authorization.
- Every externally-visible claim carries an `Evidence` reference.

## Roles / processes

| Process | Command | Responsibility |
|---------|---------|----------------|
| API | `entrypoint.sh api` | HTTP API, dashboard backend, health probes |
| Bot | `entrypoint.sh bot` | Telegram update loop, command router, job creation |
| Worker | `entrypoint.sh worker` | Job execution: collect → normalize → validate → store → correlate |
| Migrate | `entrypoint.sh migrate` | `alembic upgrade head`, then exit |

## IOC intelligence (Phase 5)

`intelligence/ioc/` is a `NORMALIZE → STORE → CORRELATE` step, not a collector:

```
stored public message text
        │  extract_iocs()  (pure, defang-aware, overlap-resolved, deduped)
        ▼
IocEnricher (runs inside IngestionService, and standalone for re-processing)
        ├── IOC row (get_or_create, normalized)            ── dedup
        ├── typed entity  Domain / URL / IP  (+ IOC.linked_entity_*)
        ├── Evidence  { entity=IOC, source=message, reference, raw=±60-char snippet }  ── immutable
        └── Relationship  MESSAGE_CONTAINS_{IOC,DOMAIN,IP,URL} / MESSAGE_MENTIONS_USERNAME
```

Bios/descriptions get a lighter pass (`enrich_entity_text`) →
`ACCOUNT_LINKED_TO_WEBSITE` / `DOMAIN_REFERENCED_BY_ACCOUNT`. Reads go through
`IocService` (per message, per container, recent). Every IOC keeps its evidence;
nothing is inferred without a source reference.

## Background jobs (Phase 8)

```
bot handler (/search, /username, …)
   │  submit_job(kind, params={query, user_id, chat_id})
   ▼
Job row (PENDING) ──enqueue──► queue (Redis list / in-memory)
                                   │  worker: dequeue
                                   ▼
                            JobRunner._process
                              RUNNING ─► handler (fresh session, progress ticks)
                                 │
                       ok ──► COMPLETED (+ result summary)
                       err ─► FAILED ─► PENDING (re-enqueue, backoff 5·2ⁿ s) up to max_retries
                                   │
                                   ▼
                        Notification ─► Bot.send_message(chat_id, rendered result)
```

The bot never blocks: a long command replies "queued" immediately.
Cancellation (`/cancel`, `POST /jobs/{id}/cancel`) sets `CANCELLED`; the runner
skips it before pickup and after completion. `/message` and `/history` stay
synchronous (DB-only).

## Reports (Phase 10)

```
/report @x  ─►  Report row + resolved Target  ─►  report_generate job
                                                     │
                              ReportBuilder.build() ─┤ 15 sections, evidence-linked claims
                                                     ▼
                          render_json / render_html (escaped) / render_pdf (fpdf2)
                                                     ▼
                    REPORTS_DIR/<id>/report.{json,html,pdf}  +  Report.content_json
                                                     ▼
                              DM summary  ·  GET /api/v1/reports/{id}/download?fmt=
```

Every material claim is tagged `FACT` / `INFERENCE` / `UNKNOWN` and carries the
`evidence` ids that support it. Unknown data is reported as `UNKNOWN`, never
fabricated. HTML output escapes all collected text.

## Watchlist monitoring (Phase 9)

```
worker loop tick (every ≤60 s)
   │  schedule_due_watches(): active entries where last_checked_at < now − interval
   ▼
watch_poll job (per entry) ─► WatchMonitor.poll(entry)
   │   re-collect public presence (telegram channel/group msgs, username platforms)
   │   diff vs last_seen_marker {telegram_max_msg_id, platforms}
   │   advance marker; stamp last_checked_at
   ▼
Activity[] ─► "NEW PUBLIC ACTIVITY" ─► Bot.send_message(user.telegram_user_id)
```

Only public sources; nothing here reads private content. `last_seen_marker`
guarantees no duplicate notifications. Per-user cap
(`RATE_LIMIT_WATCH_MAX_TARGETS`) enforced at add time.

## Entity resolution, graph & timeline (Phase 7)

```
Target (per user)
   │  TargetResolver.resolve()  → TARGET_IS_ACCOUNT / TARGET_HAS_USERNAME (+ evidence)
   ▼
resolved entities ── GraphService.for_target() ─► bounded BFS (depth≤3, node cap)
                  └─ TimelineService.for_target() ─► events from evidence.observed_at,
                                                     message.posted_at, relationship.first_seen,
                                                     account first-observed → sorted, by_year
```

`merge_entities(keep, drop)` is the only operation that mutates a persisted
`Evidence` row (repointing `entity_id`), gated by `allow_evidence_repointing()`;
it also repoints `relationship` and `message` references and collapses the
resulting self-loops / duplicate edges.

## Phase 1 implementation notes

- `security/config.py` — single typed settings source (`pydantic-settings`),
  secrets as `SecretStr`, wildcard-CORS rejected at load, production secret gate.
- `security/logging.py` — `structlog`, JSON in prod, `request_id`/`job_id` bound
  via `contextvars`.
- `database/` — `Base` with naming convention, engine/session with sqlite +
  Postgres support, `Job` and `AuditLog` operational tables, Alembic wired to
  application settings.
- `apps/api` — app factory, request-context middleware, config-driven CORS,
  `/health` + `/ready`.
