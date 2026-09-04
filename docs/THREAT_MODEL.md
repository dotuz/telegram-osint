# Threat Model

Format: **Threat → attack surface → impact → mitigation → test**. Items marked
_(planned)_ land in the referenced phase.

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
| 9 | Malicious OSINT content | Collected text/media | Downstream injection, poisoning | Treat collected data as inert; validate/normalise; content hashing | `tests/unit/test_normalizers_*` _(P4)_ |
| 10 | Prompt injection | Collected content → AI layer | AI follows attacker instructions | Content is data not instruction; system-prompt isolation; evidence-linked claims only | `tests/security/test_prompt_injection_*` _(P6)_ |
| 11 | API abuse / scraping | All endpoints | Cost, rate exhaustion, source bans | Sliding-window per-principal + per-IP limits (Redis, in-memory fallback); login IP limit | `test_rate_limiting.py` ✅ |
| 12 | Rate-limit bypass | Header spoofing, distributed IPs | Abuse despite limits | Limit keyed on authenticated principal, not just IP; per-IP key is a wide backstop only | `test_rate_limiting.py::test_limit_is_per_principal_not_only_ip` ✅ |
| 13 | Compromised external source | GitHub/Reddit/web responses | Poisoned data, malicious payloads | Per-source confidence; schema validation; size caps; no eval of responses | `tests/unit/test_collector_validation_*` _(P6)_ |
| 14 | Malicious collector / dependency | Supply chain | Code execution in worker | Pinned deps; collectors return DTOs (no DB/eval access); review | dependency audit in CI _(P12)_ |
| 15 | Data poisoning | Repeated crafted public posts | Wrong correlations / reports | Evidence immutability + new observations; confidence decay; manual review flag | `tests/unit/test_confidence_*` _(P6)_ |
| 16 | Privilege escalation | Role checks, admin endpoints | Admin takeover | Role taken from signed token only (dev-shim role untrusted in prod); `require_admin` on every admin route; audit log | `test_idor_bola.py::test_audit_is_admin_only`, `test_auth_hardening.py::test_role_claim_cannot_be_self_elevated` ✅ |
| 17 | Stack-trace / info leak | API errors, bot replies | Recon aid | Generic user-facing errors; details only in logs; security headers strip framing | `test_injection.py`, `test_headers_origin_csrf.py` ✅ |
| 18 | Scope violation (privacy) | Collectors, operator account | Legal/ethical breach | Hard "never" list in code review; operator account gated by explicit env config; `UNKNOWN` over guessing | manual + `tests/e2e` scope assertions |
| 19 | Refresh-token theft / replay | Stolen cookie or body token | Silent session persistence | Rotating single-use refresh tokens (SHA-256 stored); replay of a spent token revokes the whole family; `logout` revokes | `test_refresh_rotation.py` ✅ |

## Trust boundaries

1. Telegram user ↔ bot (only Bot API data; allow-listed users).
2. Bot/API ↔ job queue/workers (internal network).
3. Workers ↔ external sources (SSRF-guarded egress, treated as hostile).
4. API ↔ dashboard browser (CORS + CSRF + auth).
5. App ↔ database (least-privilege DB user; parameterised access).
