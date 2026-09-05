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

Allow-list by default (`apps/bot/auth.py`):

| Telegram id in… | Resolved role | Can use |
|---|---|---|
| `TELEGRAM_ADMIN_USER_IDS` | `ADMIN` | all commands, unlimited |
| `TELEGRAM_ALLOWED_USER_IDS` (not admin) | `ANALYST` | all non-admin commands, unlimited |
| neither, `PUBLIC_BOT_ENABLED=false` (default) | — | nothing (generic denial + audit entry) |
| neither, `PUBLIC_BOT_ENABLED=true` | `USER` | all non-admin commands, **free-tier limited** (see below) |

If **no** ids are configured and `PUBLIC_BOT_ENABLED=false` (the default) the
bot rejects everyone and logs `bot_allowlist_empty` at startup. Authorization
here is for UX; the API/worker layers re-check every resource server-side
(Phase 12).

### Public tier (`PUBLIC_BOT_ENABLED=true`)

Opens the bot to any Telegram user as `Role.USER`, capped by a free-action
quota so it can't be used to flood the job queue or external OSINT sources
for free indefinitely:

- `FREE_OSINT_ACTIONS` (default 3) collection actions (`/search`, `/user`,
  `/group`, `/channel`, `/username`, `/report`) per Telegram user, tracked on
  `user.free_actions_used`.
- Once spent, the bot replies with a referral link
  (`https://t.me/<bot_username>?start=ref_<telegram_id>`). When
  `REFERRAL_UNLOCK_COUNT` (default 5) **distinct** people `/start` the bot via
  that link, the referrer is unlocked permanently (the count is computed
  live from `user.invited_by_telegram_id`, so it never needs resetting and
  never regresses). Self-referral and re-recording an existing referral are
  both rejected.
- A paid "subscribe to skip the limit" path is intentionally **not**
  implemented yet — it needs a payment provider decision (Telegram Stars is
  the simplest, no external merchant account) before it can be built for
  real; the bot currently shows "tez orada" (coming soon) for it.
- Allow-listed users (`TELEGRAM_ALLOWED_USER_IDS`/`TELEGRAM_ADMIN_USER_IDS`)
  are **always** unlimited regardless of this switch — add someone there to
  give them unlimited access without going through the referral flow.
- The existing per-command bot rate limit (`RATE_LIMIT_BOT_PER_MINUTE`) still
  applies on top of the quota, for every tier.

See `apps/bot/quota.py`, `database/repositories/users.py`, and
`tests/integration/test_public_bot.py`.

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
| `/watch` `/unwatch` `/watchlist` | 9 ✅ | Monitor public handles; worker polls every `WATCH_POLL_INTERVAL_SECONDS` and DMs "NEW PUBLIC ACTIVITY". Capped by `RATE_LIMIT_WATCH_MAX_TARGETS` |
| `/report @username` · `/report list` | 10 ✅ | Async 15-section report (JSON/HTML/PDF); worker DMs a summary, download via the API |
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
