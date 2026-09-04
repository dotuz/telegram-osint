# Threat Model

Format: **Threat → attack surface → impact → mitigation → test**. Items marked
_(planned)_ land in the referenced phase.

| # | Threat | Attack surface | Impact | Mitigation | Test |
|---|--------|----------------|--------|-----------|------|
| 1 | Unauthorized access | Bot commands, API, dashboard | Data exposure, abuse | Bot allow-list IDs; server-side RBAC; session auth _(P12)_ | `tests/security/test_authz_*` _(P12)_ |
| 2 | IDOR / BOLA | API resource endpoints | Cross-workspace data read/write | All queries scoped to principal; never trust client IDs | `tests/security/test_idor_*` _(P12)_ |
| 3 | Credential / secret exposure | Logs, error responses, repo | Full compromise | `SecretStr`; secret gate; gitleaks in CI; `.env` ignored | `test_config.py::test_secrets_are_not_printed` ✅ |
| 4 | CSRF | Cookie-auth browser endpoints | State change as victim | CSRF token + SameSite + Origin/Referer checks _(P12)_ | `tests/security/test_csrf_*` _(P12)_ |
| 5 | CORS misconfiguration | API CORS layer | Credentialed cross-origin theft | Explicit allow-list; wildcard rejected at load | `test_cors_and_secrets.py` ✅ |
| 6 | SSRF | Web/OSINT URL fetcher | Internal network access, metadata theft | Scheme allow-list, DNS + private-range block, redirect re-check, size/timeout caps _(P4/P12)_ | `tests/security/test_ssrf_*` _(P4)_ |
| 7 | SQL injection | Any DB query path | Data exfiltration / tamper | Parameterised queries only; repositories; `ruff S608` | `tests/security/test_sqli_*` _(P4)_ |
| 8 | XSS | Dashboard rendering, report HTML | Session theft, defacement | React auto-escaping; sanitised report HTML; CSP _(P11)_ | `tests/security/test_xss_*` _(P11)_ |
| 9 | Malicious OSINT content | Collected text/media | Downstream injection, poisoning | Treat collected data as inert; validate/normalise; content hashing | `tests/unit/test_normalizers_*` _(P4)_ |
| 10 | Prompt injection | Collected content → AI layer | AI follows attacker instructions | Content is data not instruction; system-prompt isolation; evidence-linked claims only | `tests/security/test_prompt_injection_*` _(P6)_ |
| 11 | API abuse / scraping | All endpoints | Cost, rate exhaustion, source bans | Per-user/IP/command/source rate limits _(P12)_ | `tests/security/test_rate_limit_*` _(P12)_ |
| 12 | Rate-limit bypass | Header spoofing, distributed IPs | Abuse despite limits | Limit on authenticated principal, not just IP; Redis counters | `tests/security/test_rate_limit_bypass_*` _(P12)_ |
| 13 | Compromised external source | GitHub/Reddit/web responses | Poisoned data, malicious payloads | Per-source confidence; schema validation; size caps; no eval of responses | `tests/unit/test_collector_validation_*` _(P6)_ |
| 14 | Malicious collector / dependency | Supply chain | Code execution in worker | Pinned deps; collectors return DTOs (no DB/eval access); review | dependency audit in CI _(P12)_ |
| 15 | Data poisoning | Repeated crafted public posts | Wrong correlations / reports | Evidence immutability + new observations; confidence decay; manual review flag | `tests/unit/test_confidence_*` _(P6)_ |
| 16 | Privilege escalation | Role checks, admin endpoints | Admin takeover | Server-side role checks on every admin route; audit log | `tests/security/test_privesc_*` _(P12)_ |
| 17 | Stack-trace / info leak | API errors, bot replies | Recon aid | Generic user-facing errors; details only in logs | `tests/security/test_error_leak_*` _(P12)_ |
| 18 | Scope violation (privacy) | Collectors, operator account | Legal/ethical breach | Hard "never" list in code review; operator account gated by explicit env config; `UNKNOWN` over guessing | manual + `tests/e2e` scope assertions |

## Trust boundaries

1. Telegram user ↔ bot (only Bot API data; allow-listed users).
2. Bot/API ↔ job queue/workers (internal network).
3. Workers ↔ external sources (SSRF-guarded egress, treated as hostile).
4. API ↔ dashboard browser (CORS + CSRF + auth).
5. App ↔ database (least-privilege DB user; parameterised access).
