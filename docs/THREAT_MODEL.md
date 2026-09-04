# Threat Model

Format: **Threat → attack surface → impact → mitigation → test**. Items marked
_(planned)_ land in the referenced phase.

Reconciled against the implementation in Phase 13 (final QA). See
`PHASE_13_FINAL_QA_REPORT.md` for the full evidence trail.

| # | Threat | Attack surface | Impact | Mitigation | Test |
|---|--------|----------------|--------|-----------|------|
| 1 | Unauthorized access | Bot commands, API, dashboard | Data exposure, abuse | Bot allow-list IDs; server-side RBAC; signed access tokens; dev shim disabled in prod | `test_auth_hardening.py` ✅ |
| 2 | IDOR / BOLA | API resource endpoints | Cross-workspace data read/write | All queries scoped to principal; never trust client IDs; jobs scoped to requester | `test_idor_bola.py` ✅ |
| 3 | Credential / secret exposure | Logs, error responses, repo | Full compromise | `SecretStr`; secret gate; gitleaks in CI; `.env` ignored | `test_config.py::test_secrets_are_not_printed`, `test_cors_and_secrets.py` ✅ |
| 4 | CSRF | Cookie-auth browser endpoints | State change as victim | Refresh cookie `HttpOnly; Secure; SameSite=Strict` scoped to `/api/v1/auth`; Origin check on state-changing verbs | `test_headers_origin_csrf.py` ✅ |
| 5 | CORS misconfiguration | API CORS layer | Credentialed cross-origin theft | Explicit allow-list; wildcard rejected at load | `test_cors_and_secrets.py` ✅ |
| 6 | SSRF | Web/OSINT URL fetcher | Internal network access, metadata theft | Scheme allow-list, DNS + private-range block, redirect re-check, size/timeout caps | `tests/unit/test_ssrf_fetcher.py` ✅ |
| 7 | SQL injection | Any DB query path | Data exfiltration / tamper | Parameterised queries only; repositories; `ruff S608` | `test_injection.py` ✅ |
| 8 | XSS | Dashboard rendering, report HTML | Session theft, defacement | React auto-escaping; `html.escape` on every report field; CSP `default-src 'none'` | `test_injection.py::test_xss_in_report_html_is_escaped` ✅ |
| 9 | Malicious OSINT content | Collected text/media | Downstream injection, poisoning | Treat collected data as inert; validate/normalise; content hashing; collectors return DTOs only | `tests/unit/test_normalize.py`, `tests/unit/test_username_adapters.py` ✅ |
| 10 | Prompt injection | Collected content → AI/NLP layer | AI follows attacker instructions | No LLM is wired in; the "AI analysis" step is deterministic confidence scoring over evidence rows, never free-text instruction-following. `assert_safe_phrasing()` guards report output. | `tests/unit/test_confidence_engine.py` ✅ (residual: revisit if an LLM is added) |
| 11 | API abuse / scraping | API endpoints **and bot commands** | Cost, rate exhaustion, source bans | API: sliding-window per-principal + per-IP limits (Redis, in-memory fallback). Bot: per-Telegram-user, per-command sliding window in the `authorized` guard (`RATE_LIMIT_BOT_PER_MINUTE`). Login IP limit. | `test_rate_limiting.py`, `test_bot_rate_limit.py` ✅ |
| 12 | Rate-limit bypass | Header spoofing, distributed IPs | Abuse despite limits | Limit keyed on authenticated principal, not just IP; per-IP key is a wide backstop only | `test_rate_limiting.py::test_limit_is_per_principal_not_only_ip` ✅ |
| 13 | Compromised external source | GitHub/Reddit/web responses | Poisoned data, malicious payloads | Per-source confidence; schema validation; size caps (`HTTP_FETCH_MAX_BYTES`); no eval of responses; SSRF guard | `tests/unit/test_ssrf_fetcher.py`, `tests/unit/test_username_adapters.py` ✅ |
| 14 | Malicious collector / dependency | Supply chain | Code execution in worker | Version-floored deps + lockfile in CI; collectors return DTOs (no DB/eval access); review. Automated `pip-audit` / `npm audit` recommended in CI (not yet wired). | manual review; `.github/workflows/ci.yml` gitleaks ✅ / dep-audit ⚠ |
| 15 | Data poisoning | Repeated crafted public posts | Wrong correlations / reports | Evidence immutability (`before_flush` listener); confidence never asserts identity; manual review flag | `tests/unit/test_evidence_immutability.py`, `tests/unit/test_confidence_engine.py` ✅ |
| 16 | Privilege escalation | Role checks, admin endpoints | Admin takeover | Role taken from signed token only (dev-shim role untrusted in prod); `require_admin` on every admin route; audit log | `test_idor_bola.py::test_audit_is_admin_only`, `test_auth_hardening.py::test_role_claim_cannot_be_self_elevated` ✅ |
| 17 | Stack-trace / info leak | API errors, bot replies | Recon aid | Generic user-facing errors; details only in logs; security headers strip framing | `test_injection.py`, `test_headers_origin_csrf.py` ✅ |
| 18 | Scope violation (privacy) | Collectors, operator account | Legal/ethical breach | Hard "never" list in code review; operator account gated by explicit env config; `UNKNOWN` over guessing | manual + `tests/e2e/test_full_pipeline.py` phrasing assertions |
| 19 | Refresh-token theft / replay | Stolen cookie or body token | Silent session persistence | Rotating single-use refresh tokens (SHA-256 stored); replay of a spent token revokes the whole family; `logout` revokes; `SELECT ... FOR UPDATE` serialises concurrent rotations | `test_refresh_rotation.py`, `test_refresh_concurrency.py` ✅ |
| 20 | Queue/DB divergence | Redis outage at submit time | Orphaned PENDING jobs, lost work | `get_default_queue()` probes Redis and falls back to in-memory; `submit_job` marks a job FAILED if enqueue raises (no silent orphan) | `test_queue_resilience.py` ✅ |
| 21 | Shared intelligence graph enumeration | `/iocs`, `/entities/*`, message/graph reads | One analyst sees entities another researched | **By design** — the dedup entity graph is shared across authenticated analysts; only the per-user layer (targets/searches/watchlists/reports) is scoped. Acceptable for a single-team deployment; a multi-tenant deployment needs graph partitioning. | documented; `test_idor_bola.py` covers the per-user layer |

## Trust boundaries

1. Telegram user ↔ bot (only Bot API data; allow-listed users; per-command rate limit).
2. Bot/API ↔ job queue/workers (internal network; enqueue failure surfaces, never silently drops).
3. Workers ↔ external sources (SSRF-guarded egress, treated as hostile).
4. API ↔ dashboard browser (CORS + Origin check + Bearer access token + HttpOnly refresh cookie).
5. App ↔ database (parameterised access; FK + unique constraints enforced; verified on PostgreSQL 18).

## Known residual risks (accepted)

- **DNS rebinding / TOCTOU in `SafeFetcher`** — the pre-flight resolve and httpx's
  own connect-time resolve are separate lookups; a rebinding attacker could pass
  the check then connect to a private IP. Mitigation would need a pinned-IP
  transport. Impact bounded by no-eval, size/redirect caps, text-only handling.
- **`SafeFetcher` buffers the full response** before truncating to
  `HTTP_FETCH_MAX_BYTES` (not a streaming abort) — a hostile endpoint can force a
  large download. Bounded by the total timeout.
- **Access token in dashboard `localStorage`** — XSS-exfiltratable; mitigated by
  short TTL, HttpOnly refresh cookie, and strict API CSP. Documented design.
- **Login brute force is IP-limited only** (no pre-auth principal). No
  account-lockout by design (avoids lockout-DoS).
- **Reverse-proxy deployments** must run uvicorn with `--proxy-headers` and a
  trusted-hosts list, or every client shares one rate-limit IP key. Not
  auto-detected.
