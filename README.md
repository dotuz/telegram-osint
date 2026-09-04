# Telegram OSINT Intelligence Platform

Public-data intelligence and research platform. A Telegram bot + backend that lets
**authorized** users search, correlate, analyze, monitor, and report on **public**
Telegram information and other **public** OSINT sources.

> **Scope boundary.** This platform works with (1) data the bot legitimately
> receives via the Telegram Bot API, (2) publicly accessible Telegram content,
> (3) public OSINT sources, and (4) an explicitly authorized operator account
> where the operator has legally configured one. It **never** performs session/
> token theft, credential harvesting, OTP interception, account takeover, malware
> delivery, or scraping of private content. See [`docs/SECURITY.md`](docs/SECURITY.md).

---

## Status

| Phase | Scope | State |
|------:|-------|-------|
| 1 | Foundation: config, logging, DB + migrations, tests, CI, Docker | ✅ done |
| 2 | Telegram bot: `/start`, `/help`, menu, router, auth, error handling | ✅ done |
| 3 | Database: full domain models, repositories, indexes, constraints | ✅ done |
| 4 | Public Telegram intelligence (user/group/channel/message search) | ✅ done |
| 5 | IOC extraction (URL/domain/IP/email/hash/CVE/Telegram) | ✅ done |
| 6 | Username OSINT + source-adapter architecture | ⛏ next |
| 7 | Entity resolution, graph, timeline | ☐ |
| 8 | Background workers (Redis jobs, retries, cancellation) | ☐ |
| 9 | Watchlist / monitoring | ☐ |
| 10 | Reports (PDF / HTML / JSON) | ☐ |
| 11 | Web dashboard (Next.js) | ☐ |
| 12 | Security hardening (RBAC, CSRF, CORS, SSRF, rate limits, IDOR) | ☐ |
| 13 | Final QA | ☐ |

## Architecture (short)

Modular monolith with hard module boundaries so components can be split into
services later. `Telegram User → Bot → API/Application → (Auth | Job Queue) →
Workers → (Telegram | OSINT | Intelligence) collectors → Database → (Search |
Graph | Reports) → Dashboard`. Full detail in
[`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md).

**Stack:** Python 3.12, FastAPI, SQLAlchemy 2, PostgreSQL, Redis, Celery/worker
queue, Pydantic, `python-telegram-bot`; Next.js + TypeScript + Tailwind for the
dashboard; Docker Compose for local dev.

## Quick start (local, Docker)

```bash
cp .env.example .env
# edit .env: set SECRET_KEY (python -c "import secrets;print(secrets.token_urlsafe(64))")
#            set TELEGRAM_BOT_TOKEN, TELEGRAM_ALLOWED_USER_IDS, TELEGRAM_ADMIN_USER_IDS
docker compose up --build
# API:      http://localhost:8000/health
# API docs: http://localhost:8000/docs   (disabled when APP_ENV=production)
```

## Quick start (local, no Docker)

```bash
python -m venv .venv && . .venv/bin/activate      # .venv\Scripts\activate on Windows
pip install -e ".[dev]"
cp .env.example .env                              # then edit as above
# Point DATABASE_URL at a local Postgres, or use sqlite for a quick look:
#   DATABASE_URL=sqlite+pysqlite:///./local.sqlite3
alembic upgrade head
make run-api        # or: uvicorn apps.api.main:app --reload
```

## Tests

```bash
make test           # full suite (unit + integration + security), fully offline
make test-unit      # fast unit tests only
make test-sec       # security regression tests
make cov            # with coverage
```

The unit suite needs **no** external services — it runs against in-memory SQLite.

## Repository layout

```
apps/            bot/ api/ dashboard/         entrypoints
workers/                                       background job workers
collectors/      telegram/ username/ github/ reddit/ web/ common/
intelligence/    entity_resolution/ relationships/ timeline/ confidence/ ioc/ classification/
reports/                                       PDF/HTML/JSON report generation
database/        base.py session.py models/ repositories/ migrations/
security/        config.py logging.py  (+ auth/RBAC/SSRF in later phases)
tests/           unit/ integration/ security/ e2e/
docker/          Dockerfile entrypoint.sh
docs/            ARCHITECTURE SECURITY THREAT_MODEL DATABASE API DEPLOYMENT DEVELOPMENT COLLECTORS
```

## Documentation

- [ARCHITECTURE.md](docs/ARCHITECTURE.md) — components, boundaries, data flow
- [SECURITY.md](docs/SECURITY.md) — security assumptions, the hard "never" list, controls
- [THREAT_MODEL.md](docs/THREAT_MODEL.md) — threats, attack surface, mitigations, tests
- [DATABASE.md](docs/DATABASE.md) — schema, indexes, retention
- [DEVELOPMENT.md](docs/DEVELOPMENT.md) — local setup, conventions, phase workflow
- [DEPLOYMENT.md](docs/DEPLOYMENT.md) — production deployment, secrets, scaling
- [API.md](docs/API.md) — HTTP API surface
- [COLLECTORS.md](docs/COLLECTORS.md) — the collector interface and how to add a source
- [BOT.md](docs/BOT.md) — Telegram bot setup, commands, authorization model
