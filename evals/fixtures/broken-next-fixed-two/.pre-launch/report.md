# Pre-Launch Report — broken-next
Last run: 2026-09-03T12:00:00Z · Domains: security, data, seo, compliance, payments, hygiene · Tiers: static
Since last run: 0 resolved · 0 new · 0 regressed · 6 open

## Launch readiness
Blockers (critical, open): 4

| ID | Title | Domain | Status |
|---|---|---|---|
| SEC-001 | No hardcoded secrets or API keys in source | security | fail |
| SEC-051 | Webhook signature verification on every webhook handler | security | fail |
| DAT-001 | RLS (or equivalent rules) enabled on every table holding user data | data | fail |
| COMP-001 | Privacy policy exists and matches actual data practices | compliance | fail |

| Severity | fail | attest | pass | skipped | error |
|---|---|---|---|---|---|
| critical | 4 | 0 | 0 | 0 | 0 |
| high | 1 | 0 | 0 | 0 | 0 |
| medium | 1 | 0 | 0 | 0 | 0 |
| low | 0 | 0 | 0 | 0 | 0 |

## Security
### Open
- **SEC-001** No hardcoded secrets or API keys in source — critical — easy — app/api/webhooks/stripe/route.ts:2 — sk_live_ literal
- **SEC-051** Webhook signature verification on every webhook handler — critical — guided — route.ts:4 parses JSON before verification
- **SEC-035** CORS not wildcard; credentials handling correct — high — easy — route.ts:6 Access-Control-Allow-Origin: *

## Data
### Open
- **DAT-001** RLS (or equivalent rules) enabled on every table holding user data — critical — guided — 0001_init.sql:3 disables RLS on documents

## Compliance
### Open
- **COMP-001** Privacy policy exists and matches actual data practices — critical — guided — no privacy page found

## SEO
### Open
- **SEO-009** Custom 404 page returning a real 404 status — medium — easy — no app/not-found.tsx
