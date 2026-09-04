# Database

## Engine

PostgreSQL 16 in every real environment. The **unit test suite** runs against
in-memory SQLite; migrations are also tested on SQLite (file) and on Postgres in
CI. `security.config.Settings.is_sqlite` toggles engine-specific behaviour
(foreign-key PRAGMA, static pool for `:memory:`).

## Conventions

- Base class: `database/base.py::Base`, with an explicit constraint
  **naming convention** so Alembic diffs are stable.
- `TimestampMixin` → `created_at`, `updated_at` (server defaults).
- `SoftDeleteMixin` → `deleted_at` where soft deletion is meaningful
  (targets, reports, watchlist, search history).
- Primary keys: UUID strings (`new_uuid()`), except natural external keys.
- JSON payloads stored as `Text` for portability across PG/SQLite in early
  phases; migrate hot paths to `JSONB` in Phase 3.
- No raw SQL string building — everything via SQLAlchemy Core/ORM.

## Migrations

```bash
alembic upgrade head                       # apply
alembic revision --autogenerate -m "msg"   # generate (review the diff!)
alembic downgrade -1                        # roll back one
```

`database/migrations/env.py` pulls the URL from `Settings`, imports
`database.models` so autogenerate sees all tables, and uses
`render_as_batch=True` for SQLite compatibility.

## Tables

### Phase 1 (operational)

| Table | Purpose | Key indexes |
|-------|---------|-------------|
| `job` | Background job records + state machine | `(state, kind)`, `requested_by`, `created_at` |
| `audit_log` | Append-only security audit trail | `actor`, `action`, `resource`, `created_at` |

`job.state ∈ {PENDING, RUNNING, COMPLETED, FAILED, CANCELLED}` (CHECK constraint);
`job.progress ∈ [0,100]` (CHECK constraint).

### Phase 3 (domain) — migration `0002_domain_schema`

Three layers:

| Layer | Tables | Scoping |
|-------|--------|---------|
| Identity | `user` | — |
| Per-user investigation | `target`, `search`, `search_result`, `watchlist`, `report` | `user_id` (workspace) |
| Shared intelligence graph | `telegram_account`, `telegram_group`, `telegram_channel`, `message`, `username`, `external_account`, `domain`, `url`, `ip`, `ioc`, `relationship`, `evidence` | global, deduplicated |

**Unique constraints prevent duplicate entities:**

| Table | Uniqueness |
|-------|-----------|
| `user` | `email` |
| `telegram_account` / `telegram_group` / `telegram_channel` | `telegram_id` |
| `username` | `(platform, value_normalized)` |
| `external_account` | `(platform, identifier_normalized)` |
| `domain` | `name_normalized` |
| `url` | `url_hash` (sha256 of normalized URL) |
| `ip` | `address` (normalized) |
| `ioc` | `(ioc_type, value_normalized)` |
| `message` | `(source_type, source_id, message_id)` |
| `relationship` | `(source_type, source_id, target_type, target_id, rel_type)` |
| `evidence` | `(entity_type, entity_id, field, source, content_hash)` — an *observation* key |
| `target` / `watchlist` | `(user_id, kind, value_normalized)` |

Every dedup column stores a **normalized** form (`database/normalize.py`);
`get_or_create_*` in the repositories is the only way to create these rows.

**Indexes** (§17): `username.value_normalized`, `*.telegram_id`,
`message.message_id`, `message.(source_type, source_id)`, `domain.name_normalized`,
`ip.address`, `ioc.value_normalized`, `evidence.observed_at`,
`evidence.collected_at`, plus `created_at` on the per-user tables and
`relationship` source/target/last_seen.

**Graph model.** `relationship` is a directed edge between any two entities
(`entity_type` + `entity_id`). `RelationshipRepository.observe()` creates the edge
or bumps `last_seen` / `observation_count` (keeping `first_seen`, taking the max
`confidence`) — it never duplicates.

**Job state machine.** `job.state` transitions are guarded by `JobRepository`
(`PENDING→RUNNING→{COMPLETED,FAILED,CANCELLED}`, `FAILED→PENDING` for retry);
illegal transitions raise `IllegalJobStateTransition`.

## Evidence immutability

`evidence` rows are write-once. When observed data changes, a **new** evidence /
observation row is inserted — historical observations are never overwritten or
silently mutated. This is enforced at runtime by a SQLAlchemy `before_flush`
listener (`database/models/evidence.py::block_evidence_mutation`): modifying or
deleting a persisted `Evidence` raises `EvidenceImmutableError`.

## Retention (Phase 12)

Configurable retention windows; deletion of targets / search history / evidence /
reports respects FK constraints and soft-delete semantics. Personal data is not
retained indefinitely.
