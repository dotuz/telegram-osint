# Collectors

A **collector** gathers data from exactly one source and returns normalised,
validated records plus **evidence**. Collectors are independent of the
intelligence engine and of the database schema — the worker persists their
output.

## Interface (`collectors/common`, finalised in Phase 6)

```python
class Collector(Protocol):
    name: str  # stable slug, e.g. "github", "telegram_public"
    source_type: str  # "telegram" | "external_account" | "web" | ...

    async def collect(self, request: CollectRequest) -> CollectResult:
        """Fetch raw data for the request. Network-bound. Must respect timeouts,
        rate limits, and the SSRF guard for any URL fetch."""

    def normalize(self, raw: RawRecords) -> list[NormalizedRecord]:
        """Pure function: raw payload -> canonical records. No I/O."""

    def validate(self, records: list[NormalizedRecord]) -> list[NormalizedRecord]:
        """Drop/flag malformed or implausible records. No I/O."""

    async def health_check(self) -> HealthStatus:
        """Is the source reachable / are credentials valid? For /sources/health."""
```

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
| `telegram_public` | Public Telegram (Bot API + optional operator acct) | 4 | bot token / operator |
| `github` | GitHub public profiles, repos, gists | 6 | optional `GITHUB_TOKEN` |
| `reddit` | Reddit public posts/comments | 6 | optional app creds |
| `web` | Generic public web pages | 6 | none |
| `username_x`, `username_instagram`, `username_youtube`, `username_tiktok` | Public presence checks | 6+ | none / optional |

## Adding a source

1. Create `collectors/<slug>/` with a class implementing `Collector`.
2. Register it in the adapter registry (Phase 6) — no core-engine changes.
3. Add unit tests: `normalize` and `validate` with fixture payloads; a mocked
   `collect`; a `health_check` test.
4. Document it in the table above.
