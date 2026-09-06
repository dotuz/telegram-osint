# Refactor Report — Telegram Public OSINT Investigator

**Date:** 2026-09-06 · **Version:** 0.15.0 · **Base:** `5e2176e` (Phase 14)

---

## 1. Existing Architecture

Modular monolith, one backend image running three roles (`api` / `bot` /
`worker`). Reused verbatim in this refactor:

| Layer | Modules | Status |
|---|---|---|
| Config / logging | `security/config.py`, `security/logging.py` (structlog, `SecretStr`) | kept |
| Auth / RBAC | `security/auth.py` (scrypt + HMAC tokens + rotating refresh), `apps/api/deps.py`, `apps/bot/auth.py` (allow-list + public tier) | kept |
| Rate limiting | `security/ratelimit.py` (sliding window, Redis + in-memory), API + bot guards | kept |
| Security middleware | `apps/api/security.py` (headers, Origin check, `rate_limit()`) | kept |
| Database | SQLAlchemy 2.0 models, Alembic (`0001`–`0004`), repository layer, `ScopedRepository` BOLA guard, evidence `before_flush` immutability | kept + extended |
| Job system | `workers/` (`JobQueue` Redis/in-memory, `JobRunner`, `@register`, retry/backoff, cancellation) | kept + new job kind |
| Collectors | `collectors/common/` (`Collector` ABC, `SafeFetcher` SSRF guard), `collectors/telegram/`, `collectors/username/` | kept, reused |
| Intelligence | `intelligence/` — `entity_resolution`, `relationships` (graph), `timeline`, `confidence` (never asserts identity), `ioc` | kept, reused |
| Reports | `reports/` — `ReportContent`, JSON/HTML(escaped)/PDF renderers | kept + new builder |
| Dashboard | Next.js 14 App Router (`apps/dashboard/`) | kept (see §14) |
| Audit | `database/models/audit_log.py`, `AuditRepository` (key-scrubbing) | kept |

## 2. Old Product Direction

"Telegram OSINT Intelligence Platform" — a **generic multi-source** OSINT
platform. The bot exposed ~20 mostly-independent commands (`/search`, `/user`,
`/group`, `/channel`, `/message`, `/username`, `/watch`, `/report`, …). There
was no single "run an investigation on this identifier" concept; a user had to
chain commands and assemble the picture themselves. `Target` + `Search` +
`Report` existed as separate per-user rows with no aggregate tying them.

## 3. New Product Direction

**Telegram Public OSINT Investigator.** One input — a Telegram `@username` or
numeric user id — one output: an **Investigation** with the target's publicly
observable footprint, classified observations, a timeline, correlated
entities, public IOCs, an overall confidence, and an evidence-backed report
that always states its visibility limitations.

```
/investigate @example
  → INV-xxxxxxxx (QUEUED → RUNNING → COMPLETED)
  → [1] normalize  [2] public footprint  [3] mentions  [4] messages
    [5] entity correlation  [6] report
  → structured bot summary + JSON/HTML/PDF report
```

## 4. Refactored Components

| Component | Change |
|---|---|
| `database/types.py` | `+ InvestigationStatus`, `+ ObservationType` (AUTHOR/MENTION/REPLY/REFERENCE/UNKNOWN), `+ ObservationResourceKind` |
| `database/models/investigation.py` | **new** — `Investigation` (scoped to `user_id`, `public_id` `INV-xxxxxxxx`, status, `job_id`, `report_id`, `confidence`, `summary_json`) + `InvestigationObservation` (CASCADE, `observation_type`, `resource_*`, `snippet`, `observed_at`, `source`, `confidence`) |
| `database/migrations/versions/0005_investigations.py` | **new** — both tables + indexes; verified up/down + `alembic check` clean on SQLite and PostgreSQL 18 |
| `database/repositories/investigation_repo.py` | **new** — `InvestigationRepository(ScopedRepository)`: `create`, `get`/`get_by_public_id` (owner-scoped → `None` for others), `set_status`, `add_observation`, `observations` |
| `intelligence/investigation/target.py` | **new** — `parse_target()` normalisation + validation (§7) |
| `intelligence/investigation/classifier.py` | **new** — `classify_observation()` (§11) |
| `intelligence/investigation/service.py` | **new** — `InvestigationService` orchestrator (§8) reusing `TelegramPublicCollector`, `UsernameOsintService`, `extract_iocs`, confidence engine |
| `reports/models.py` | `+ INVESTIGATION_SECTION_ORDER` + new section keys/titles; `as_dict()` now emits any registered section in order (legacy 15-section report unchanged) |
| `reports/investigation_report.py` | **new** — `generate_investigation_report()` → `Report` row + JSON/HTML/PDF artifacts via the existing renderers |
| `workers/handlers.py` | `+ @register("investigation")` |
| `apps/bot/handlers/investigate.py` | **new** — `/investigate` command + bare-command text follow-up |
| `apps/bot/app.py` / `router.py` | `investigate` registered as the primary command; text `MessageHandler` for the target follow-up; `/start` + `/help` lead with it |
| `apps/bot/intel_views.py` | `+ render_investigation_started`, `+ render_investigation_result` |
| `apps/bot/views.py` | product name → "Telegram Public OSINT Investigator"; `/start` body reframed |
| `apps/api/routers/investigations.py` | **new** — create+queue / list / detail / report download, scoped + rate-limited |
| `apps/api/main.py` | mounts the investigations router |

**Nothing was deleted.** The Phase 4–10 commands and their services still work
and are what the orchestrator calls internally.

## 5. Telegram Capabilities (what the system can actually do)

| Capability | Mechanism | Availability |
|---|---|---|
| Resolve a public `@username` / public chat metadata | Bot API `getChat` (`BotApiTelegramSource`) | **AVAILABLE** when `TELEGRAM_BOT_TOKEN` is set and the handle is public |
| Public profile fields (title, description, member count, verified/scam flags) | Bot API `getChat` | **AVAILABLE** (subset; depends on chat type) |
| Public message / mention / reply search across Telegram | authorized operator account (`TELEGRAM_OPERATOR_*`, MTProto `SearchGlobal`) **or** a seeded/indexed source | **AVAILABLE only** with an operator account or a configured source; otherwise **NOT OBSERVABLE** |
| Public web-indexed Telegram pages (t.me previews, third-party indexes) | SSRF-guarded `SafeFetcher` + a web collector | framework present; specific indexers are a follow-up (§19) |
| Cross-platform username correlation (GitHub/Reddit/…) | `UsernameOsintCollector` + confidence engine | **AVAILABLE**, always as *potential match*, never confirmed identity |
| Public IOC extraction from observed text | `intelligence/ioc/extract.py` | **AVAILABLE** |
| Timeline of time-stamped public observations | `InvestigationService` + observation `observed_at` | **AVAILABLE** |

## 6. Telegram Limitations (honestly reported, never fabricated)

The report and the bot response always carry these; when a step can't run it
says `NOT OBSERVABLE`, not "nothing found":

- Private groups and private chats cannot be verified.
- Absence of an observation does not prove absence of activity.
- Deleted or edited public content may not be recoverable.
- Comprehensive public message/mention search requires an authorized operator
  account; the **Bot API cannot search public messages** — without an operator
  account, message/mention discovery is limited to the configured source and is
  frequently `NOT OBSERVABLE`.
- A username match across platforms is a *potential* match, never a confirmed
  identity.

**Never implemented** (spec §24, §32): session strings, auth keys, OTP,
passwords, cookies, private chat/channel/group history, account takeover,
malware, credential collection, `get_all_joined_groups(user_id)` and similar
fictitious APIs.

## 7. Bot UX

```
/start        → product intro, leads with /investigate
/help         → command list (investigate first; /search etc. marked "advanced")
/investigate  → the investigation flow (primary command; counts against the
                public free-tier quota)
/report       → generate a legacy dossier report for a target (kept)
/history      → your recent searches
/whoami       → your Telegram id + role
admin: /admin /health /jobs /stats /audit /users
```

Interaction:

```
User:  /investigate @example
Bot:   🔎 Investigation started
       Target: @example
       ID: INV-1A2B3C4D
       Collecting public Telegram intelligence…
       [1/6] Target normalization … [6/6] Report generation
       I'll send the results here when it finishes.
   (worker completes)
Bot:   🔎 Investigation INV-1A2B3C4D — 3 public observation(s) for @example; 1 likely authored; 1 mention(s); 1 repl(y/ies).
       ✓ Target normalized … ✓ Evidence correlated
       Public resources: 1   Message observations: 3
       Mentions: 1   Replies: 1   Likely authored: 1
       Cross-platform aliases: 2   IOCs: 0
       Overall confidence: 85
       ⚠ Private groups and private chats cannot be verified by this investigation.
```

Nothing found:

```
Bot:   🔎 Investigation INV-…
       No publicly observable Telegram activity was discovered.
       This does NOT prove the target has no Telegram activity. Private
       resources and inaccessible historical content cannot be verified.
```

Bare `/investigate` → prompts, and the next plain-text message is the target.

## 8. Investigation Workflow

`InvestigationService.run(investigation_id)` (async, driven by the worker):

1. **`RUNNING`**, then `parse_target()` — bad target → `FAILED` with a message,
   no fabricated output.
2. **Public footprint** — `TelegramPublicCollector.run(KIND_USER)`. If the
   collector returns `no public Telegram source is configured`, `source_configured
   = False` and a `NOT OBSERVABLE` limitation is added.
3. **Mentions / 4. Messages** — `TelegramPublicCollector.run(KIND_MESSAGE_SEARCH)`.
   Each returned message record → `classify_observation()` → an
   `InvestigationObservation` row (type + confidence + resource + snippet +
   `observed_at` + source).
4. **Entity correlation** — for username targets, `UsernameOsintService.run()`
   → potential cross-platform aliases with per-source confidence (the existing
   confidence engine; it never emits "the same person"). IOCs extracted from
   observed snippets.
5. **Confidence** — `min(95, max(signal))` over AUTHOR/REPLY observation
   confidences + alias confidence; MENTION signals capped at 60; `None` when no
   source is configured (→ "NOT OBSERVABLE" in the report, not "0").
6. **Report** — `generate_investigation_report()` writes the JSON/HTML/PDF
   artifacts and links `investigation.report_id`. A report failure is logged
   and noted but does **not** fail the investigation.
7. **`COMPLETED`**; `summary_json` holds counts, narrative, limitations, notes,
   profile, aliases, IOCs.

State machine: `QUEUED → RUNNING → {COMPLETED, FAILED}`; `CANCELLED` via the
job. Bound to a `Job` (`kind="investigation"`) so retries/cancellation/worker
restart all work through the existing Phase-8 infrastructure.

## 9. Collector Architecture

Unchanged `Collector` ABC (`collect → normalize → validate → run`, never
raises). The orchestrator calls two collectors:

- **`TelegramPublicCollector`** — backed by a `TelegramSource`:
  `FakeTelegramSource` (tests/demos), `BotApiTelegramSource` (public `getChat`;
  **cannot search messages** — returns `[]`, documented), or an operator-account
  source where legally configured. `KIND_USER`, `KIND_GROUP`, `KIND_CHANNEL`,
  `KIND_MESSAGE_SEARCH`.
- **`UsernameOsintCollector`** — pluggable per-platform adapters; each outbound
  request goes through the SSRF-guarded `SafeFetcher`.

No collector accesses private data. Adding a public-web Telegram index is a
matter of writing one more adapter behind `SafeFetcher` (§19).

## 10. Evidence Model

Kept: the append-only, write-once `Evidence` table with a `before_flush`
immutability listener (`EvidenceImmutableError`) and per-observation
`content_hash`. Every collector emits `EvidenceDraft`s that the ingestion layer
persists with `source`, `source_type`, `observed_at`, `confidence`, `reference`.

New: `InvestigationObservation` is the investigation-scoped "public
observation" record — `observation_type`, `resource_kind`, `resource_ref`,
`resource_url`, `message_ref`, `snippet`, `observed_at`, `source`, `confidence`,
optional `evidence_id`. It CASCADE-deletes with its investigation and never
mutates the shared graph.

## 11. Entity Resolution & the Authorship/Mention Distinction

`classify_observation(target, author_username, author_id, text, is_reply,
reply_to_author)` → `(ObservationType, confidence)`:

| Result | Condition | conf |
|---|---|---|
| `AUTHOR` | the observation's own `author_username` normalises to the target (or `author_id` == target id) | 92 |
| `REPLY` | `is_reply` **and** (reply-to author is the target **or** the body mentions the target) | 70 |
| `MENTION` | the body `@`-mentions the target (and it is not AUTHOR) | 80 |
| `REFERENCE` | the target appears as bounded plain text / a `t.me/<target>` link | 55 |
| `UNKNOWN` | an association is observed but its nature can't be established | ~30 |

A `MENTION` is **never** upgraded to `AUTHOR` — the author check is strict
equality on the author field and runs first
(`tests/unit/test_observation_classifier.py::test_mention_is_never_promoted_to_author`,
`::test_mention_does_not_beat_author_when_both_present`).

Cross-platform identity: the confidence engine's forbidden-phrase guard
(`assert_safe_phrasing`) still rejects "the same person" / "confirmed identity"
/ "definitely" in any report narrative; alias bands are `username_only` … `high`
with the explicit label *"Do not assume the same person."*

## 12. Timeline

Built from the `observed_at` of the classified observations, sorted ascending,
each event = `{when, type, source, url, confidence}`. Rendered as the
`timeline` report section and summarised in the bot response.

## 13. Reports

`reports/investigation_report.py` produces the spec §18 layout, reusing the
existing `render_json` / `render_html` (HTML-escaped) / `render_pdf` (fpdf2)
renderers:

`Executive Summary · Target Information · Public Profile · Observed Public
Resources · Public Message Activity · Mentions · Replies · Timeline · Entities ·
Relationships · Evidence · Confidence · **Data Visibility Limitations** ·
Methodology · Audit Information`

Every section separates `FACT` from `INFERENCE` from `UNKNOWN`. The limitations
section is always populated. Artifacts land in `REPORTS_DIR/<report_id>/` and
are downloadable via `GET /api/v1/investigations/{id}/report/download?fmt=…`
(owner-scoped).

## 14. Dashboard

**Not refactored in this phase.** The Next.js dashboard still builds
(`npm install` / `tsc` / `next build` all green from Phase 13) and its existing
pages (targets, search, reports, jobs, …) still function against the unchanged
Phase 4–11 API. An investigation-centric dashboard (an Investigations list +
an INV detail page: Target → Profile → Resources → Messages → Mentions →
Timeline → Entity graph → Evidence → Report) is the recommended next piece of
work — the API it needs (`/api/v1/investigations*`) already exists and is
tested. Status: **READY WITH LIMITATIONS** for the dashboard specifically; the
primary UX (the bot) is fully working.

## 15. Security Review

Full `tests/security/` suite re-run after the refactor — **all pass** (39
tests): IDOR/BOLA, auth hardening (forged/expired/tampered tokens, prod dev-shim
disabled), rate limiting (per-principal + per-IP), Origin/CSRF, headers, CORS,
refresh rotation + concurrency (Postgres), injection (SQLi params/body inert,
report HTML XSS-escaped), secret non-exposure.

Refactor-specific checks:

- **IDOR/BOLA** — `InvestigationRepository` is a `ScopedRepository`; `get` /
  `get_by_public_id` filter on `user_id` and return `None` for a non-owner. API
  endpoints 404 for non-owners. Covered by
  `test_investigation_flow.py::test_investigation_is_scoped_to_its_owner` and
  the E2E cross-user block.
- **Telegram input validation** — `parse_target` rejects empty / control chars
  / over-long / non-Telegram URL / space / `select * from users` / bad
  username shape / invalid id (`test_investigation_target.py`, 17 cases). The
  lossy `normalize_username` can no longer turn junk into a "valid" username
  (raw-charset check added).
- **SSRF** — no new URL-fetching code path; the username collectors still go
  through `SafeFetcher`. `parse_target` accepts only `t.me` / `telegram.me` /
  `telegram.dog` hosts for the link form.
- **XSS** — investigation report HTML uses the same escaped renderer;
  `classify_observation` snippets are truncated and stored as text, never
  rendered as markup.
- **Rate limiting** — the API `/investigations` router carries
  `rate_limit("investigate", …)`; the bot `/investigate` command carries
  `quota=True` (public free-tier) on top of `RATE_LIMIT_BOT_PER_MINUTE`.
- **Audit** — `investigation_created` is audit-logged (bot); job lifecycle
  through the existing job audit path.
- **Privacy boundary** — reviewed every new module: no session/token/OTP/
  cookie/private-history access, no fictitious enumeration APIs.

## 16. Tests

| Area | File | Count |
|---|---|---|
| Target normalization / validation | `tests/unit/test_investigation_target.py` | 17 |
| Observation classification | `tests/unit/test_observation_classifier.py` | 9 |
| Investigation orchestration + IDOR + "NOT OBSERVABLE" | `tests/integration/test_investigation_flow.py` | 4 |
| E2E `/investigate` → worker → report → API → cross-user | `tests/e2e/test_investigation_e2e.py` | 1 |
| Existing suite (regression) | all of `tests/` | unchanged, green |

Gate: `ruff check` ✅ · `ruff format --check` ✅ · `mypy` (145 files) ✅ ·
`alembic upgrade head` / `alembic check` ✅ (SQLite **and** PostgreSQL 18) ·
`pytest` **335 passed / 1 skipped** on SQLite, **336 passed** on PostgreSQL 18.

## 17. E2E Results

`tests/e2e/test_investigation_e2e.py::test_investigate_end_to_end` — **PASS**.
Real code path, synthetic collectors only:

```
/investigate @alice (bot handler, allow-listed user)
  → Investigation row created (INV-…), job kind "investigation" enqueued
  → JobRunner.run_once() → InvestigationService.run()
      → TelegramPublicCollector(FakeTelegramSource) → 3 messages
      → classify: 1 AUTHOR (author=alice), 1 MENTION (@alice by mallory), (+ reply case in the flow test)
      → UsernameOsintService (alice_collector) → 2 potential aliases
      → generate_investigation_report → JSON/HTML/PDF on disk
  → bot notification: "Investigation INV-… … Mentions: 1 … Likely authored: 1"
API (bearer token for the resolved bot user):
  GET /api/v1/investigations            → 1, status COMPLETED
  GET /api/v1/investigations/{id}        → observations incl. AUTHOR + MENTION;
                                           "the same person" absent
  GET …/report/download?fmt=json|html    → 200, correct content-type;
                                           sections include "limitations" + "methodology"
Different user:
  list → []   detail → 404   report download → 404
```

## 18. Remaining Risks

1. **Message/mention discovery depends on a configured source.** With only the
   Bot API, `KIND_MESSAGE_SEARCH` returns nothing and the investigation
   correctly reports `NOT OBSERVABLE`. This is honest, but it means the
   headline feature is thin until an operator account or a public-web index
   collector is wired. Not a defect — a deployment/coverage reality,
   prominently documented.
2. **DNS-rebinding / streaming-size caveats in `SafeFetcher`** — unchanged from
   Phase 13's residual-risk list; still bounded by no-eval + timeout + redirect
   caps.
3. **`public_id` uniqueness** — `INV-` + 8 hex chars from `secrets.token_hex`;
   collision probability negligible, no unique-index retry logic (the index
   would raise and the job would fail cleanly on the ~1-in-4-billion event).
4. **Dashboard is not investigation-shaped yet** (§14).
5. **Multi-worker scheduler race** — unchanged, low impact.

## 19. Unsupported Capabilities

Marked `UNAVAILABLE WITH CURRENT TELEGRAM ACCESS MODEL` and not faked:

- Enumerating every group/channel a user has joined.
- Private group/channel membership or history.
- Private chat history, deleted/edited private messages.
- Any account credential, session, auth key, OTP, or cookie.
- "All mentions ever" without an operator account or a comprehensive public
  index (the Bot API cannot search).

Closest legitimate equivalents implemented: public `getChat` profile
resolution; classified public message/mention/reply observations from whatever
public source is configured; cross-platform username correlation; a public
IOC/timeline/entity picture; an evidence-backed report that states exactly what
it could and could not see.

Recommended follow-ups (not blockers): a public-web Telegram index collector
(tgstat-style / `site:t.me` style) behind `SafeFetcher`; an operator-account
source doc + guard; the investigation-centric dashboard.

## 20. Final Status

# READY WITH LIMITATIONS

The core investigation flow — **Telegram username / ID → Investigation → public
observations → resources → messages/mentions/replies → evidence → timeline →
confidence → report** — works end-to-end (verified by an executed E2E test on
both SQLite and PostgreSQL 18), through the real bot / job / worker / collector
/ report / API code paths.

The product is honest about visibility: no fabricated Telegram capabilities, no
private-account access, no session/credential/OTP handling, and an explicit
`NOT OBSERVABLE` wherever the current access model cannot see something.

The "with limitations" qualifier is for: (a) comprehensive public
message/mention discovery requiring a configured operator account or a
public-web index collector that is not yet wired, and (b) the dashboard not yet
being investigation-shaped (its API exists and is tested). Neither blocks the
primary bot experience.
