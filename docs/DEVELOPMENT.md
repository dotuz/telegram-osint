# Development

## Prerequisites

- Python 3.11+ (3.12 recommended — matches the Docker image)
- Docker + Docker Compose (optional, for the full stack)
- Node 20+ (only for `apps/dashboard`, Phase 11)

## Setup

```bash
python -m venv .venv
. .venv/bin/activate            # Windows: .venv\Scripts\activate
pip install -e ".[dev]"
cp .env.example .env
```

Generate a secret key:

```bash
python -c "import secrets; print(secrets.token_urlsafe(64))"
```

### Database

- Quick look: `DATABASE_URL=sqlite+pysqlite:///./local.sqlite3`
- Realistic: `docker compose up db redis -d` then
  `DATABASE_URL=postgresql+psycopg://osint:osint@localhost:5432/telegram_osint`

```bash
alembic upgrade head
```

## Common tasks

| Command | Does |
|---------|------|
| `make run-api` | uvicorn with reload |
| `make run-bot` | Telegram bot (Phase 2+) |
| `make run-worker` | job worker (Phase 8+) |
| `make test` | full suite |
| `make test-unit` / `make test-sec` | subset by marker |
| `make lint` / `make fmt` | ruff |
| `make typecheck` | mypy |
| `make revision m="..."` | autogenerate a migration |

## Conventions

- **No giant files.** One responsibility per module.
- **No duplicate implementations.** Search before adding; prefer a shared service.
- Collectors implement the `collectors/common` interface and stay independent of
  `intelligence/` and the DB schema (return DTOs + evidence).
- Handlers (bot/API) never block on collection — enqueue a `Job`.
- Every external input gets a Pydantic schema. Parameterised queries only.
- Every user-visible claim carries an evidence reference. `UNKNOWN` is a valid,
  expected answer — never fabricate.
- Tests are written **before** a module is considered complete. New behaviour
  ships with unit tests; security-relevant behaviour ships with a
  `@pytest.mark.security` test.

## Phase workflow (per `START NOW` rules)

1. Inspect repo & dependencies. 2. Short plan. 3. Smallest coherent change.
4. Run tests. 5. Fix failures. 6. Security review. 7. Update docs.
8. Report files changed / decisions / DB changes / security / tests / TODOs.
9. Only then continue to the next phase.

## Test markers

`unit` (fast, isolated) · `integration` (DB/Redis) · `security` (IDOR, CSRF,
CORS, SSRF, ...) · `e2e` (bot/API flows). Select with `pytest -m <marker>`.
