# Collectors

A **collector** gathers data from exactly one source and returns normalised,
validated records plus **evidence**. Collectors are independent of the
intelligence engine and of the database schema — the worker persists their
output.

## Interface (`collectors/common/interfaces.py` — implemented in Phase 4)

```python
class Collector(abc.ABC):
    name: str                      # stable slug, e.g. "telegram_public"
    source_type: str               # SourceType value
    supported_kinds: frozenset[str]

    async def collect(self, request: CollectRequest) -> RawBundle:      # network-bound
    def normalize(self, raw: RawBundle) -> list[NormalizedRecord]:      # pure
    def relationships(self, raw, records) -> list[RelationshipDraft]:   # pure, optional
    def validate(self, records) -> list[NormalizedRecord]:             # pure; dedups, drops empty keys
    async def health_check(self) -> HealthStatus

    async def run(self, request) -> CollectResult   # orchestrates the above; never raises
```

`run()` is what callers use: unsupported kind → `ok=False`; any exception in
`collect` → `ok=False` with the message; otherwise `normalize`+`validate`+
`relationships`. Collectors return **DTOs + evidence drafts only** — the
`IngestionService` (`intelligence/ingest.py`) persists them.

### DTOs

| DTO | Purpose |
|-----|---------|
| `CollectRequest` | `query`, `kind`, `limit`, `since`, `options` |
| `RawBundle` | opaque payload from `collect` → `normalize` (`payload`, `error`, `notes`, `partial`) |
| `NormalizedRecord` | `ref` (local id), `entity_type`, `natural_key` (dedup), `attributes`, `evidence` |
| `EvidenceDraft` | `ref`, `field`, `value`, `source`, `reference`, `observed_at`, `confidence`, `raw` |
| `RelationshipDraft` | `source_ref`, `target_ref`, `rel_type`, `confidence` |
| `CollectResult` | `ok`, `records`, `relationships`, `partial`, `error`, `notes` |

### Registry

`collectors/common/registry.py` — `registry.register(collector)`;
`registry.for_kind(kind)`; `await registry.health()`. Built-ins are registered by
`collectors/bootstrap.py::register_default_collectors()` at process start.

### Every result record carries

`source`, `username` (or entity ref), `url`/`reference`, `discovered_at`,
`evidence`, `confidence`.

### Evidence (`security` + `database`, Phase 16)

`id`, `source`, `source_type`, `reference`, `collected_at`, `observed_at`,
`content_hash`, `extraction_method`, `confidence`, `metadata`. Immutable after
collection; changes create a new observation.

## Rules

- **Public data only.** No auth/session/OTP/cookie handling. No private content
  without an explicitly authorized operator account.
- Never assume two accounts are the same person on a username match alone —
  emit a correlation candidate with evidence + confidence, not a fact.
- Degrade gracefully: one failed source never discards another's results.
- All outbound HTTP goes through the SSRF-guarded fetcher in
  `collectors/common` (scheme allow-list, private-range block, redirect
  re-validation, size/timeout caps, logging).
- Respect each source's ToS and rate limits; back off on `429`.

## Planned collectors

| Slug | Source | Phase | Auth |
|------|--------|------:|------|
| `telegram_public` | Public Telegram (Bot API + optional operator acct) | 4 ✅ | bot token / operator |
| `username_osint` | Fan-out over all username adapters | 6 ✅ | — |

**Username adapters** (`collectors/username/`, registered on `username_registry`):

| Platform | Endpoint | Auth |
|----------|----------|------|
| `github` | `api.github.com/users/{u}` | optional `GITHUB_TOKEN` |
| `reddit` | `reddit.com/user/{u}/about.json` | none |
| `telegram` | public profile/chat lookup | bot token / operator |
| `x` `instagram` `youtube` `tiktok` `keybase` `gitlab` | `WebProbeAdapter` (200 vs 404 + negative-marker check) | none |

Every HTTP adapter fetches through `SafeFetcher` (SSRF-guarded). Correlation
confidence and `ACCOUNT_POSSIBLY_SAME_AS` edges are added by
`intelligence/username_osint.py`, not the collector — collectors stay
independent of the intelligence engine.

### Telegram sources (`collectors/telegram/source.py`)

The collector depends only on the `TelegramSource` protocol, so it is fully
testable offline:

| Source | Coverage | When used |
|--------|----------|-----------|
| `OperatorTelegramSource` | best (history, search) | `TELEGRAM_OPERATOR_*` set + library installed (not yet wired) |
| `BotApiTelegramSource` | public chat metadata only | `TELEGRAM_BOT_TOKEN` set |
| `NullTelegramSource` | none | nothing configured |
| `FakeTelegramSource` | seeded in-memory | tests / local demos |

## Adding a source

1. Create `collectors/<slug>/` with a class implementing `Collector`.
2. Register it in `collectors/bootstrap.py` — no core-engine changes.
3. Add unit tests: `normalize`/`validate` with fixture payloads; a fake data
   source; a `health_check` test.
4. Document it in the tables above.
