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

### Phase 3 (domain — planned)

`user`, `target`, `telegram_account`, `telegram_group`, `telegram_channel`,
`message`, `username`, `external_account`, `domain`, `url`, `ip`, `ioc`,
`relationship`, `evidence`, `search`, `search_result`, `watchlist`, `report`.

Planned unique constraints prevent duplicate entities, e.g.
`telegram_account.telegram_id`, `username(value, platform)`, `domain.name`,
`ip.address`, `ioc(type, value)`, `message(source_id, message_id)`.

Planned indexes: `username`, `telegram_id`, `message_id`, `source_id`, `domain`,
`ip`, `ioc.value`, `created_at`, `observed_at`.

## Evidence immutability

`evidence` rows are write-once. When observed data changes, a **new** evidence /
observation row is inserted — historical observations are never overwritten or
silently mutated.

## Retention (Phase 12)

Configurable retention windows; deletion of targets / search history / evidence /
reports respects FK constraints and soft-delete semantics. Personal data is not
retained indefinitely.
