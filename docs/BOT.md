# Telegram Bot

## Setup

1. Create a bot with [@BotFather](https://t.me/BotFather) → get the token.
2. Find your numeric Telegram user id (e.g. via [@userinfobot](https://t.me/userinfobot)).
3. In `.env`:
   ```
   TELEGRAM_BOT_TOKEN=123456:AA...
   TELEGRAM_ALLOWED_USER_IDS=11111111,22222222
   TELEGRAM_ADMIN_USER_IDS=11111111
   ```
4. Run: `make run-bot` (local) or `docker compose up bot`.

The bot uses **long polling** by default. For production behind a proxy, a
webhook with a secret path is preferred (Phase 12).

## Authorization model

Allow-list only (`apps/bot/auth.py`):

| Telegram id in… | Resolved role | Can use |
|---|---|---|
| `TELEGRAM_ADMIN_USER_IDS` | `ADMIN` | all commands |
| `TELEGRAM_ALLOWED_USER_IDS` (not admin) | `ANALYST` | all non-admin commands |
| neither | — | nothing (generic denial + audit entry) |

If **no** ids are configured the bot rejects everyone and logs
`bot_allowlist_empty` at startup. Authorization here is for UX; the API/worker
layers re-check every resource server-side (Phase 12).

## Commands

Source of truth: `apps/bot/router.py`. `/help` is generated from it and hides
admin commands from non-admins. Commands whose phase has not shipped yet reply
with a short "scheduled for phase N" message and the planned usage — the command
surface is complete and discoverable without fabricating functionality.

| Command | Phase | Notes |
|---|---|---|
| `/start` | 2 ✅ | Title + body + inline main menu |
| `/help` | 2 ✅ | Dynamic command list |
| `/whoami` | 2 ✅ | Your Telegram id + role |
| `/admin` | 2 ✅ | Admin overview (admin only) |
| `/health` | 2 ✅ | DB + Redis checks (admin only) |
| `/search` `/user` `/group` `/channel` | 4 ✅ (Phase 8: enqueued) | Public Telegram intel — replies "queued", worker delivers the result |
| `/message` `/history` | 4 ✅ | DB-only, synchronous |
| `/username` | 6 ✅ (Phase 8: enqueued) | Username OSINT across public sources |
| `/cancel` | 8 ✅ | Cancel a queued/running job by id prefix |
| `/jobs` `/stats` | 8 ✅ | (admin) recent jobs / usage + queue depth |
| `/watch` `/unwatch` | 9 | Watchlist |
| `/report` | 10 | Async report generation |
| `/settings` | 11 | User preferences |
| `/audit` `/users` | 12 | (admin) audit log, user management |

## Design

```
telegram update
   │
CommandHandler / CallbackQueryHandler        apps/bot/app.py
   │
@authorized(admin=?)  ── denial ─► generic message + audit   apps/bot/guard.py
   │  (Principal)
handler (async)                              apps/bot/handlers/*
   │  builds
BotMessage  (text + keyboard, no telegram.* types)   apps/bot/responses.py, views.py
   │
adapter.reply(update, msg)  ── edits in place for callbacks   apps/bot/adapter.py
```

- **Views are pure** (`apps/bot/views.py`): plain inputs → `BotMessage`. No I/O,
  no `telegram.*`. This is what the unit tests exercise.
- **Errors never leak.** The `@authorized` wrapper and the global
  `apps/bot/errors.py` handler turn any exception into
  `"Something went wrong… try again later."` and log full detail with
  `request_id`.
- **Long-running commands** (`long_running=True` in the registry) will enqueue a
  `Job` and return immediately (wired in Phase 8); they never block the update
  loop.
- **`/start` never asks for credentials** — enforced by
  `test_start_never_asks_for_credentials`.

## Tests

- `tests/unit/test_bot_auth.py` — role resolution, denial, empty allow-list.
- `tests/unit/test_bot_views_router.py` — view rendering, registry consistency,
  `/help` admin filtering, "no credentials" guarantee.
- `tests/integration/test_bot_handlers.py` — handlers with mock updates: menu,
  denial, admin gating, audit rows, generic-error fallback.
- `tests/integration/test_bot_app.py` — `build_application` wiring (offline).
