# Changelog

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
