# Pre-Launch Skill — Design Spec

Date: 2026-09-03
Status: draft for review

## 1. Purpose

A Claude Code skill, invoked as `/pre-launch`, that audits a web or mobile application project before it goes to production and then helps fix what it finds. It runs from the project root, always has the codebase, usually has a local dev environment, and sometimes has a staging URL. It produces a persistent readiness report and a fix workflow driven by that report.

Two phases, always separate:

1. **Audit** — runs every applicable check, writes `.pre-launch/findings.json` and `.pre-launch/report.md`. Never modifies project code.
2. **Fix** — reads the findings back, fixes them in one of three modes, re-verifies each fix, commits per finding.

## 2. Decisions made during brainstorming

| Topic | Decision |
|---|---|
| Access | Codebase always; local env usually; remote URL sometimes. Skill detects available tiers and degrades per check. |
| Audit vs fix | Audit produces report only. Fix is a separate invocation reading the report. |
| Fix modes | (a) fix all easy then guided walk, (b) fix easy, pause, then guided walk, (c) everything one by one. |
| Guided-only fixes | Auth logic, data access rules, payments, data deletion, schema changes, legal text. Never auto-applied. |
| Verification | Every fix re-runs its check. Failure reverts the change and marks `error`. |
| Commits | One commit per finding: `fix(SEC-014): <title>`. Warn once and continue without commits if not a git repo. |
| Stacks | Detect from repo; load matching stack reference files. Checks are stack-agnostic; stack files say where to look. |
| Unverifiable items | Status `attest`. Skill checks machinery exists, user confirms in report. Skill runs anything it can run locally (load test, kill switch, sign-up walk). |
| Invocation | `/pre-launch` full; `/pre-launch <domain...>` scoped; `/pre-launch fix [domain...]`; `/pre-launch config`. |
| Re-runs | Update report in place; preserve `first_seen`; compute `resolved`; print delta. |
| Local env | Detect and ask once; persist in `.pre-launch/config.yml`. |
| Architecture | Orchestrator in SKILL.md, one subagent per domain in parallel, findings merged by orchestrator. |
| External tools | Use existing tools (gitleaks, npm audit, Lighthouse, axe, autocannon/k6) rather than reimplement. Offer install; fall back to grep-based checks if declined. |

## 3. Architecture

### 3.1 File layout

```
pre-launch/
├── SKILL.md                      # entry: parse args, detect, configure, dispatch, merge, or fix
├── references/
│   ├── report-format.md          # findings.json + report.md schema; merge rules
│   ├── config-format.md          # config.yml schema and detection heuristics
│   ├── checks/
│   │   ├── security.md           # SEC
│   │   ├── data.md               # DAT
│   │   ├── performance.md        # PERF
│   │   ├── reliability.md        # REL
│   │   ├── seo.md                # SEO
│   │   ├── accessibility.md      # A11Y
│   │   ├── compliance.md         # COMP
│   │   ├── mobile.md             # MOB  (conditional: platforms includes ios/android)
│   │   ├── flows.md              # FLOW
│   │   ├── payments.md           # PAY  (conditional: features.payments)
│   │   ├── ai.md                 # AI   (conditional: features.ai)
│   │   ├── hygiene.md            # HYG
│   │   └── access.md             # ACC
│   └── stacks/
│       ├── nextjs.md  nuxt.md  sveltekit.md  remix.md  astro.md
│       ├── rails.md  django.md  laravel.md  express.md  fastapi.md
│       ├── supabase.md  firebase.md  prisma.md  drizzle.md
│       ├── stripe.md  revenuecat.md  lemonsqueezy.md
│       ├── expo.md  react-native.md  flutter.md
│       └── vercel.md  netlify.md  cloudflare.md  fly.md
├── agents/
│   └── domain-auditor.md         # prompt template for every domain subagent
└── scripts/
    └── probe_url.py              # fetch URL; emit headers, meta, OG, robots, sitemap, llms.txt as JSON
```

Stack files ship for the listed stacks in v1. Unknown stacks still run: checks fall back to generic search heuristics and the report notes "no stack reference for X; static checks used generic patterns."

### 3.2 Check format

Every check in `checks/*.md` uses this block. The subagent template, the report, and the fix phase all depend on these field names.

```markdown
### SEC-051 Webhook signature verification
severity: critical              # critical | high | medium | low
tier: local                     # static | local | remote | attest — lowest tier that can verify
fix: guided                     # easy | guided | none
when: features.payments         # optional; config expression; check is skipped when false
why: A payment webhook that does not verify its signature lets anyone mark an
  order paid by POSTing a fabricated event.
verify:
  static: Find every webhook handler (stack ref: "webhook handlers"). Confirm
    each verifies the provider signature against the raw body before parsing.
  local: POST a payload with an invalid signature to each handler. Expect 4xx.
evidence: file:line per handler and the verdict; HTTP status from the probe.
fix_hint: Use the provider SDK's constructEvent with the raw body and the
  signing secret from env. (stack ref: "webhook verification snippet")
```

Rules:
- IDs are stable forever. Removing a check retires its ID; never reuse.
- `tier: attest` means the skill can only check that machinery exists. It still records evidence.
- `verify` may list multiple tiers; the subagent uses the highest tier available and records which one in `verified_by`.
- `fix: none` marks checks that are pure attestation or that produce a measurement (e.g. load-test baseline) rather than a pass/fail defect.

### 3.3 Stack references

Stack files contain no checks. Each answers a fixed set of questions, keyed by heading so checks can reference them (`stack ref: "webhook handlers"`). Required headings per stack file:

- detection signals (files/deps that identify this stack)
- dev server start command and default port
- build command and output dir
- env var loading and public-prefix conventions (e.g. `NEXT_PUBLIC_`)
- route/handler locations: API routes, server actions, middleware
- auth: where session is read; how to add a server-side check
- webhook handlers
- webhook verification snippet
- data access layer and where policies/rules live
- file uploads
- background jobs / cron
- error handling and logging entry points
- security headers configuration location
- known traps (stack-specific footguns, e.g. Next.js `remotePatterns: '**'`, Supabase security-definer functions, Firebase App Check off, server actions without auth)
- runtime probe hints (health path, common auth cookie name)

Provider stacks (supabase, firebase, stripe, revenuecat, expo, vercel, ...) only fill the headings that apply.

### 3.4 Domain subagent

`agents/domain-auditor.md` is the prompt every domain subagent receives, with these injected: the domain check file, the matching stack files, `config.yml`, the live tiers, the shared test-account file if present, and the previous findings for this domain if any.

Fixed behaviour:
- Work through every check in file order. Never skip silently. A skipped check produces a `skipped` finding with a reason.
- One finding object per check, written to `.pre-launch/findings/<domain>.json` on completion, and progressively appended so a crash loses at most the current check.
- Mark `error` with the reason rather than guessing when a check cannot be completed.
- Cap any single runtime probe at 30 seconds; cap the domain at a configurable budget (default 20 minutes) and mark remaining checks `error: budget exceeded`.
- Never modify project files. Never write outside `.pre-launch/`.
- Runtime probes use only the test account the flows domain created, never real user data.
- For `tier: attest` checks, record what machinery evidence was found so the user can decide quickly.

### 3.5 External tools

| Purpose | Preferred tool | Fallback |
|---|---|---|
| secrets in tree and history | gitleaks (or trufflehog if present) | regex scan of tree; `git log -p` grep for common key patterns |
| dependency vulns | `npm audit` / `pnpm audit` / `pip-audit` / `bundler-audit` / `composer audit` | none; mark `error` |
| Web Vitals, basic a11y, SEO | Lighthouse via `npx lighthouse` | `probe_url.py` for SEO; a11y marked `error` |
| accessibility | `@axe-core/cli` | Lighthouse a11y category |
| load testing | autocannon (Node projects) or k6 | none; mark `error` |
| DNS/email auth | `dig` | none |

The orchestrator checks presence once and prompts once to install all missing tools. Declined tools are recorded in config under `tools.declined` so re-runs don't re-ask.

### 3.6 Bundled script

`scripts/probe_url.py` — stdlib only. Given a base URL, fetches `/`, `/robots.txt`, `/sitemap.xml`, `/llms.txt`, and a nonexistent path; emits JSON with response headers, status codes, `<title>`, meta description, canonical, OG and Twitter tags, `lang`, JSON-LD blocks, H1 count, and redirect chain. Called by SEO, security, and hygiene domains.

## 4. Config

`.pre-launch/config.yml`, written by the detect step, editable by the user.

```yaml
version: 1
stacks: [nextjs, supabase, stripe, vercel]
platforms: [web]                  # web | ios | android
local:
  url: http://localhost:3000
  start: npm run dev              # null = user starts it manually
  ready_path: /
  ready_timeout_s: 120
remote:
  url: null                       # staging/preview URL, optional
test_account:
  strategy: create                # create | provided | none
  email_pattern: prelaunch+{ts}@example.com
  credentials_env: PRELAUNCH_TEST_PASSWORD
features:
  payments: true
  subscriptions: true
  trials: true
  uploads: true
  ai: false
  user_content: true
  email_sending: true
  sms: false
  biometrics: false
  teams: false
  realtime: false
  graphql: false
  health_data: false
  minors_possible: false
  b2b: false
  multilingual: false
tools:
  declined: []
budget_minutes_per_domain: 20
skip:                              # consciously waived checks; reason appears in report
  - id: SEO-005
    reason: internal tool, not indexed
```

Detection heuristics live in `references/config-format.md`. Feature flags default from detection (Stripe dependency → payments; an AI SDK → ai; upload routes or storage buckets → uploads; org/team tables → teams). Anything undetectable defaults false and is shown to the user for correction at config time.

## 5. Findings and report

### 5.1 findings.json

```json
{
  "version": 1,
  "project": "my-app",
  "runs": [
    {"at": "2026-09-03T14:02:00Z", "domains": ["security", "data"], "tiers": ["static", "local"]}
  ],
  "findings": [
    {
      "id": "SEC-051",
      "title": "Webhook signature verification",
      "domain": "security",
      "severity": "critical",
      "status": "fail",
      "fix": "guided",
      "evidence": "app/api/webhooks/stripe/route.ts:12 parses body before constructEvent; forged POST returned 200",
      "recommendation": "Call stripe.webhooks.constructEvent with the raw body and STRIPE_WEBHOOK_SECRET before parsing.",
      "verified_by": "local",
      "first_seen": "2026-09-03T14:02:00Z",
      "last_checked": "2026-09-03T14:02:00Z",
      "resolved": null,
      "commit": null,
      "notes": null
    }
  ]
}
```

Status: `pass` verified OK · `fail` verified broken · `attest` machinery checked, needs human confirmation · `skipped` not applicable or waived (reason in `notes`) · `error` check could not run (reason in `notes`).

### 5.2 Merge rules

- Match on `id`. Preserve `first_seen` from previous. Set `last_checked` to now.
- `fail` → `pass` sets `resolved` to now. `pass` → `fail` clears `resolved` and appends "regressed" to `notes`.
- Findings for domains not in this run are carried forward unchanged.
- Attestation boxes ticked in `report.md` are read before merge and set `status: pass`, `verified_by: attested`.

### 5.3 report.md

Generated from findings.json. Structure:

```
# Pre-Launch Report — <project>
Last run: <date> · Domains: <list> · Tiers: <list>
Since last run: N resolved · N new · N regressed · N open

## Launch readiness
Blockers (critical, open): N
| ID | Title | Domain | Status |
...
Counts by severity × status table.

## Security
### Open
one line per finding: **SEC-051** Webhook signature verification — critical — fail — <evidence first line>
### Attestation
- [ ] SEC-024 MFA available for admin accounts — evidence: <what was found>
### Passed (collapsed list of IDs)
### Skipped / Error (with reasons)

## Data
...
```

Blockers first, then domains in the fixed order: security, data, payments, flows, reliability, performance, compliance, access, ai, mobile, accessibility, seo, hygiene.

## 6. Audit run

1. **Parse args.** No args → all applicable domains. Domain names → scoped. `fix` → section 7. `config` → rerun detection, show diff against existing config, ask before overwriting.
2. **Load or create config.** Detection reads package manifests, lockfiles, framework config files, `supabase/`, `firebase.json`, `prisma/`, `app.json`, `ios/`, `android/`, `pubspec.yaml`, deploy config. Ask only for local URL and start command if not inferable. Show the config and ask for corrections once.
3. **Establish tiers.** Static always. Local: if `local.url` responds, use it; else run `local.start` in background and poll `ready_path` until `ready_timeout_s`. Remote: one HEAD request. Record live tiers. If local was requested but failed, say so and continue static-only.
4. **Tool check.** Presence check for tools needed by scoped domains. One prompt to install all missing. Record declines.
5. **Test account.** If `strategy: create` and local tier is live, the flows subagent runs first (alone) through sign-up and writes `.pre-launch/test-account.json` for other domains. Other subagents wait on that file. If flows is not scoped, the orchestrator runs only FLOW-001 to produce the account.
6. **Dispatch.** Parallel subagents for all scoped domains except performance. Performance runs after all others complete so the load test does not distort their probes.
7. **Merge.** Read `findings/*.json`, apply merge rules, write `findings.json` and `report.md`. Print readiness summary and report path.
8. **Cleanup.** If the skill created the test account: if FLOW-009 (account deletion) was in scope and passed, the account is already gone; otherwise delete it via the app's deletion path or note that it remains. Stop the dev server only if the skill started it.

## 7. Fix run

`/pre-launch fix [domain...]`

1. **Load and gate.** Read findings.json; if absent, tell the user to audit first. If the newest source commit is later than the last run, mention that findings may be stale but proceed. Read ticked attestation boxes and apply.
2. **Present queue.** Open `fail` findings only, grouped easy vs guided, counts by severity. Offer modes: **all**, **easy first**, **one by one**.
3. **Easy loop** (modes all, easy first). Severity order. For each: read `fix_hint` and stack ref, make the minimal change, re-run the check's verify block at the same tier it was originally verified, on pass commit `fix(<ID>): <title>` and set `resolved` and `commit`; on fail revert working changes for that finding, set `status: error`, `notes: fix attempted, re-verify failed: <why>`, continue. Print a summary at the end. In **easy first** mode, stop here and wait.
4. **Guided loop.** Severity order. For each: show finding, evidence, recommendation, and a proposed diff or plan. Wait for yes / edit / skip. Yes → apply, re-verify, commit, mark resolved. Skip → leave open, record reason in `notes` if given. Legal text findings (COMP-001, 002, 003, 004, 005, 009, 012, 016 subject/address, 029, 030) produce a draft file under `.pre-launch/drafts/` rather than editing pages in place; they stay open until the user confirms publication.
5. **Wrap.** Regenerate report, print delta, recommend a full `/pre-launch` once the guided list is clear.

Invariants: never touch `attest` findings; never fix outside scoped domains; never leave a partially applied fix; one finding per commit.

## 8. Check inventory

Legend — Sev: C critical, H high, M medium, L low. Tier: S static, L local, R remote, A attest. Fix: E easy, G guided, — none. `when` lists the config condition if conditional.

### 8.1 Security (SEC)

| ID | Check | Sev | Tier | Fix | when |
|---|---|---|---|---|---|
| SEC-001 | No hardcoded secrets or API keys in source | C | S | E | |
| SEC-002 | No secrets in git history (rotate + purge if found) | C | S | G | |
| SEC-003 | No secrets in frontend bundle; public env prefix audit | C | S | G | |
| SEC-004 | `.env*` ignored; `.env.example` holds no real values | H | S | E | |
| SEC-005 | CI and Docker do not bake or print secrets; build logs masked | H | S | G | |
| SEC-006 | Database connection strings not exposed | C | S | G | |
| SEC-007 | Source maps not publicly served in prod | M | R | E | |
| SEC-008 | Debug pages, dev tools, GraphQL/API playgrounds off in prod | H | S | E | |
| SEC-009 | Errors do not leak stack traces or internals | H | L | E | |
| SEC-010 | Server-side auth check on every protected route, action, and RPC | C | S | G | |
| SEC-011 | Object-level authorization on reads, mutations, and subresources (IDOR) | C | L | G | |
| SEC-012 | Admin routes require admin role server-side | C | L | G | |
| SEC-013 | Internal/sensitive endpoints locked down | H | L | G | |
| SEC-014 | Cron and internal job endpoints require a secret | H | S | E | |
| SEC-015 | Rate limiting on auth, forms, expensive ops, and API | H | L | G | |
| SEC-016 | Rate limit keyed correctly behind proxy; trusted forwarded headers only | M | S | E | |
| SEC-017 | Brute-force protection on login, reset, OTP | H | L | G | |
| SEC-018 | No account enumeration via login, reset, or sign-up responses | M | L | E | |
| SEC-019 | Passwords hashed with bcrypt/argon2/scrypt; never plaintext or reversible | C | S | G | |
| SEC-020 | Max password length; email case and unicode normalization | L | S | E | |
| SEC-021 | Reset and verify tokens single-use, expiring, never logged | H | S | G | |
| SEC-022 | Reset/verify links built from configured origin, not Host header | H | S | E | |
| SEC-023 | Email verification required before sensitive actions | M | S | G | |
| SEC-024 | MFA available for admin accounts | M | A | — | |
| SEC-025 | Session cookies HttpOnly, Secure, SameSite | H | L | E | |
| SEC-026 | Session expiry; rotation on login; invalidation on logout and password change | H | S | G | |
| SEC-027 | JWT algorithm pinned, expiry set, strong secret, refresh rotation | H | S | G | |
| SEC-028 | OAuth uses state, PKCE, redirect URI allowlist | H | S | G | |
| SEC-029 | No open redirect via next/return/redirect params | M | L | E | |
| SEC-030 | CSRF protection on state-changing endpoints | H | S | G | |
| SEC-031 | Content-Security-Policy present and not trivially bypassable | M | L | G | |
| SEC-032 | HSTS with sensible max-age | M | R | E | |
| SEC-033 | nosniff, frame-ancestors, Referrer-Policy, Permissions-Policy set | M | L | E | |
| SEC-034 | HTTPS enforced with redirect; no mixed content | H | R | E | |
| SEC-035 | CORS not wildcard; credentials handling correct | H | L | E | |
| SEC-036 | Authenticated responses marked private / not CDN-cacheable | M | L | E | |
| SEC-037 | Server-side schema validation on all inputs; client validation not trusted | H | S | G | |
| SEC-038 | No SQL built by string concatenation; parameterized everywhere | C | S | G | |
| SEC-039 | NoSQL operator injection prevented | C | S | G | |
| SEC-040 | ORM dynamic where/order/select never built from raw user input | H | S | G | |
| SEC-041 | No mass assignment; request body never saved wholesale | H | S | E | |
| SEC-042 | API responses expose only needed fields (no hashes, internal IDs, other users' data) | H | S | G | |
| SEC-043 | XSS: output encoding; user content never rendered as raw HTML; dangerouslySetInnerHTML audit | C | S | G | |
| SEC-044 | No template injection, eval, or unsafe deserialization of user input | C | S | G | |
| SEC-045 | SSRF: server fetches only allowlisted hosts; image proxy and HTML-to-PDF included | H | S | G | |
| SEC-046 | Path traversal prevented on file reads and downloads | H | S | E | |
| SEC-047 | Upload validation: extension allowlist, content sniffing, no executables, size limit | C | L | G | features.uploads |
| SEC-048 | Uploads stored non-executable, separate origin/bucket, sanitized filenames | H | S | G | features.uploads |
| SEC-049 | SVG uploads sanitized or blocked; images re-encoded; image lib patched | M | S | E | features.uploads |
| SEC-050 | Private files served via signed, expiring URLs | H | S | G | features.uploads |
| SEC-051 | Webhook signature verification on every webhook handler | C | L | G | |
| SEC-052 | Constant-time comparison for tokens and signatures | M | S | E | |
| SEC-053 | ReDoS on user-input regexes; zip bomb limits; XXE disabled | M | S | E | |
| SEC-054 | GraphQL: introspection off in prod; depth and complexity limits; batching limits | H | S | E | features.graphql |
| SEC-055 | Realtime/websocket channels authorized per user | H | S | G | features.realtime |
| SEC-056 | Third-party script inventory; SRI on static third-party scripts | M | R | E | |
| SEC-057 | Dependency audit: no known critical/high vulns; lockfile committed | H | S | G | |
| SEC-058 | Email header injection prevented in contact/notification forms | M | S | E | features.email_sending |
| SEC-059 | Admin actions and impersonation audit-logged | M | S | G | |
| SEC-060 | Default admin credentials changed; no seed users with known passwords in prod | C | A | G | |
| SEC-061 | Teams: org-scoped role checks; invite links expire; removal revokes access immediately | C | L | G | features.teams |
| SEC-062 | Third-party API keys scoped to minimum, server-only, rotatable | M | S | G | |
| SEC-063 | Bot protection (Turnstile/hCaptcha/reCAPTCHA) on sign-up, login, and public forms; disposable-email handling | H | L | G | |
| SEC-064 | No tokens, secrets, or PII in URLs or query strings | M | S | E | |
| SEC-065 | Version-disclosing headers removed (X-Powered-By, Server) | L | R | E | |
| SEC-066 | No sensitive paths publicly served: .git, .env, backups, config dumps, directory listings | C | R | E | |
| SEC-067 | Request body size limits enforced | M | S | E | |

### 8.2 Data (DAT)

| ID | Check | Sev | Tier | Fix | when |
|---|---|---|---|---|---|
| DAT-001 | RLS (or equivalent rules) enabled on every table holding user data | C | S | G | |
| DAT-002 | Policies tested as anon, as owner, as another user, for select/insert/update/delete | C | L | G | |
| DAT-003 | Firebase rules contain no `if true`; rules tested | C | S | G | stacks includes firebase |
| DAT-004 | Service-role / admin credentials never reach the client | C | S | G | |
| DAT-005 | Storage buckets private by default; per-bucket policies | C | S | G | |
| DAT-006 | No sensitive files in any public bucket | H | L | G | |
| DAT-007 | Views and security-definer functions bypass RLS only intentionally | H | S | G | |
| DAT-008 | Database not reachable from public internet; connection pooling in place | H | A | — | |
| DAT-009 | Indexes on foreign keys and hot query columns | M | S | E | |
| DAT-010 | No N+1 queries in list endpoints | M | L | G | |
| DAT-011 | Pagination with max page size on every list endpoint | M | S | E | |
| DAT-012 | No row-at-a-time writes in loops; batched | M | S | E | |
| DAT-013 | Transactions around multi-step writes | H | S | G | |
| DAT-014 | Unique and foreign-key constraints enforced at DB level | M | S | E | |
| DAT-015 | Migrations committed, apply cleanly to a fresh DB, rollback plan exists | H | L | G | |
| DAT-016 | No seed or test data in production | H | A | — | |
| DAT-017 | Preview/branch deployments do not use the production database | C | S | G | |
| DAT-018 | Backups automated, off-site, encrypted, retention set; storage objects included | C | A | — | |
| DAT-019 | Restore rehearsed; time-to-restore recorded | C | A | — | |
| DAT-020 | Account deletion cascades to every table and to storage objects | C | L | G | |
| DAT-021 | PII inventory exists; sensitive fields encrypted at rest | M | S | G | |
| DAT-022 | Retention and purge jobs for logs, soft-deleted rows, stale sessions | M | S | G | |
| DAT-023 | Timestamps stored in UTC | L | S | E | |
| DAT-024 | Database region matches residency claims in privacy policy | M | A | — | |
| DAT-025 | Soft vs hard delete consistent with privacy policy promises | M | S | G | |
| DAT-026 | Application DB user has least privilege; not superuser | H | S | G | |
| DAT-027 | Per-user storage and record quotas to prevent abuse | M | S | G | features.uploads or features.user_content |

### 8.3 Performance (PERF)

| ID | Check | Sev | Tier | Fix | when |
|---|---|---|---|---|---|
| PERF-001 | Load test key endpoints; record p50/p95/p99 and error rate | H | L | — | |
| PERF-002 | Slowest endpoints and single-dependency bottlenecks identified | H | L | G | |
| PERF-003 | Text responses including JSON compressed (brotli/gzip) | M | L | E | |
| PERF-004 | Cache-Control correct per asset type; hashed static assets immutable | M | L | E | |
| PERF-005 | Static assets served via CDN | M | R | G | |
| PERF-006 | CSS/JS minified; production build used | M | S | E | |
| PERF-007 | Bundle size within budget; code splitting; no dev deps in prod bundle | M | S | G | |
| PERF-008 | Images compressed, modern formats, responsive srcset, lazy below fold, dimensions set | M | S | E | |
| PERF-009 | Fonts preloaded, display swap, subset | L | S | E | |
| PERF-010 | Third-party scripts deferred; total weight known | L | R | E | |
| PERF-011 | Core Web Vitals within thresholds (LCP, CLS, INP) | H | L | G | |
| PERF-012 | Slow query log reviewed; EXPLAIN on top queries | M | L | G | |
| PERF-013 | Slow work (email, PDF, AI, exports) in background jobs, not request path | H | S | G | |
| PERF-014 | Timeouts and bounded retries on all outbound calls | H | S | E | |
| PERF-015 | Memory stable under sustained load | M | L | G | |
| PERF-016 | Serverless cold start measured and acceptable | L | R | G | |
| PERF-017 | No race conditions on payment, credit, or inventory decrement | C | S | G | |
| PERF-018 | Primary flow usable on throttled 3G | M | L | G | |
| PERF-019 | No blocking synchronous I/O in request path | M | S | E | |
| PERF-020 | Platform function timeout and payload limits respected (e.g. serverless 10s/4.5MB) | M | S | G | |

### 8.4 Reliability (REL)

| ID | Check | Sev | Tier | Fix | when |
|---|---|---|---|---|---|
| REL-001 | Crash/error reporting installed on frontend, backend, and mobile | C | S | G | |
| REL-002 | Error tracker scrubs PII; source maps uploaded privately; releases tagged | M | S | E | |
| REL-003 | Product analytics / monitoring installed | H | S | G | |
| REL-004 | Uptime monitor on public URL and critical API | H | A | — | |
| REL-005 | Alerts route to a human (pager, SMS, or push), not only a dashboard | H | A | — | |
| REL-006 | Health check endpoint exists and reflects dependency health | M | L | E | |
| REL-007 | Test keys swapped for live keys in production env; no test-key prefixes in prod config | C | A | — | |
| REL-008 | Every env var the code reads is defined for prod; no silent dev fallbacks | H | S | G | |
| REL-009 | Spend caps on every metered API; billing alerts on cloud providers | H | A | — | |
| REL-010 | Kill switch exists and toggling it takes effect | H | L | G | |
| REL-011 | Hotfix path: OTA update (mobile) or fast deploy pipeline (web) | M | S | G | |
| REL-012 | Rollback documented; previous deploy restorable in minutes | H | A | — | |
| REL-013 | CI runs tests and blocks deploy on failure; no deploys from laptops | H | S | G | |
| REL-014 | Automated tests cover critical paths: auth, payment, deletion | H | S | G | |
| REL-015 | Structured logs; no PII, tokens, or bodies logged; retention set | M | S | G | |
| REL-016 | Frontend error boundaries; graceful degradation when a third party is down | M | S | E | |
| REL-017 | TLS cert auto-renews; domain not near expiry; www/apex redirect | H | R | G | |
| REL-018 | Email deliverability: SPF, DKIM, DMARC published; bounce handling | H | R | G | features.email_sending |
| REL-019 | Scheduled jobs monitored, idempotent, non-overlapping | M | S | G | |
| REL-020 | Third-party quotas and plan tiers known and sufficient | M | A | — | |
| REL-021 | Incident comms plan; status page or equivalent | L | A | — | |
| REL-022 | Scaling plan: what breaks first at 10x | M | A | — | |
| REL-023 | Analytics funnel events fire in prod build (sign-up, purchase, key actions) | M | L | G | |
| REL-024 | Session recording masks inputs; excludes password and payment pages | H | S | E | |
| REL-025 | No PII in analytics events or URLs; IP anonymization | M | S | E | |
| REL-026 | Runbooks for top failure modes; on-call owner named | M | A | — | |
| REL-027 | Launch-day plan: DNS TTL lowered, cutover steps, rollback trigger | M | A | — | |
| REL-028 | Support flow: visible contact path, routed to a human, response target | H | S | G | |
| REL-029 | Staging mirrors prod configuration | M | A | — | |
| REL-030 | Feature flags on risky features | L | S | G | |
| REL-031 | Rebuild-from-scratch documented; env config exported; infra reproducible | M | A | — | |

### 8.5 SEO (SEO)

| ID | Check | Sev | Tier | Fix | when |
|---|---|---|---|---|---|
| SEO-001 | Unique, descriptive titles and descriptions; sane lengths | M | L | E | |
| SEO-002 | Favicon and apple-touch-icon present | L | L | E | |
| SEO-003 | sitemap.xml valid; canonical 200 URLs only; referenced from robots | M | L | E | |
| SEO-004 | robots.txt exists; does not block render assets; prod not noindex; staging noindex | H | L | E | |
| SEO-005 | llms.txt exists and is accurate | L | L | E | |
| SEO-006 | Canonical tags point to production domain | M | L | E | |
| SEO-007 | OG and Twitter tags; OG image exists at 1200×630 and returns 200 | M | L | E | |
| SEO-008 | Structured data present, relevant, and valid (Organization, WebSite, FAQ, Product, LocalBusiness, Review as applicable) | M | L | E | |
| SEO-009 | Custom 404 page returning a real 404 status | M | L | E | |
| SEO-010 | Single H1; logical heading hierarchy | L | L | E | |
| SEO-011 | hreflang correct | L | L | E | features.multilingual |
| SEO-012 | No redirect chains; trailing-slash consistency | L | R | E | |
| SEO-013 | No broken internal or external links or images | M | L | E | |
| SEO-014 | Search Console verification present | L | A | — | |
| SEO-015 | Clean URLs; no query-param duplicates without canonical | L | L | E | |
| SEO-016 | Key public pages server-render content for crawlers | M | L | G | |
| SEO-017 | Auth-only pages noindexed and excluded from sitemap | M | L | E | |

### 8.6 Accessibility (A11Y)

| ID | Check | Sev | Tier | Fix | when |
|---|---|---|---|---|---|
| A11Y-001 | axe / Lighthouse a11y scan: zero critical or serious | H | L | G | |
| A11Y-002 | Full keyboard reachability; logical focus order; no traps; skip link | H | L | G | |
| A11Y-003 | Visible focus indicators | M | L | E | |
| A11Y-004 | Contrast 4.5:1 text, 3:1 UI components | M | L | E | |
| A11Y-005 | Form labels; error messages associated; required fields marked | H | L | E | |
| A11Y-006 | Meaningful alt text; decorative images have empty alt | M | S | E | |
| A11Y-007 | `lang` attribute set | L | L | E | |
| A11Y-008 | Landmarks present; ARIA used correctly, no redundant roles | M | L | E | |
| A11Y-009 | Focus management in modals and drawers; Escape closes | M | L | G | |
| A11Y-010 | prefers-reduced-motion respected | L | S | E | |
| A11Y-011 | Usable at 200% zoom; no maximum-scale=1 | M | L | E | |
| A11Y-012 | Touch targets meet WCAG 2.2 (24px; 44px on mobile) | L | L | E | |
| A11Y-013 | Captions and transcripts for media | M | S | G | |
| A11Y-014 | Accessibility statement page | L | S | E | |
| A11Y-015 | Screen reader pass of primary flow | M | A | — | |
| A11Y-016 | Correct autocomplete attributes on auth and address forms | L | S | E | |
| A11Y-017 | Meaningful link text and button labels; no bare "click here" | L | L | E | |
| A11Y-018 | Information not conveyed by color alone | M | L | E | |

### 8.7 Compliance (COMP)

| ID | Check | Sev | Tier | Fix | when |
|---|---|---|---|---|---|
| COMP-001 | Privacy policy exists and matches actual data practices | C | S | G | |
| COMP-002 | Every third party receiving data is named (cross-check against SDK inventory) | H | S | G | |
| COMP-003 | Sale/share disclosure present if ad pixels or data-selling SDKs installed | H | S | G | |
| COMP-004 | AI use disclosed in privacy policy | M | S | G | features.ai |
| COMP-005 | Terms cover UGC, data ownership, privacy, liability limit, as-is, indemnification, termination, class waiver, arbitration, governing law; tailored to the business | C | S | G | |
| COMP-006 | Cookie/consent banner exists where required | H | L | G | |
| COMP-007 | Consent actually blocks non-essential cookies and pixels until accepted; logged; withdrawable | H | L | G | |
| COMP-008 | EULA exists and is linked from store listing | M | A | G | platforms includes ios/android |
| COMP-009 | DMCA policy, takedown clause, designated agent registered | M | S | G | features.user_content |
| COMP-010 | In-app account deletion available and discoverable | C | L | G | |
| COMP-011 | Cancellation as easy as sign-up, in-app, no dark patterns | H | L | G | features.subscriptions |
| COMP-012 | Auto-renewal terms disclosed at checkout with affirmative consent | H | S | G | features.subscriptions |
| COMP-013 | Trial reminder before conversion and annual renewal reminders; cadence meets state rules | H | S | G | features.subscriptions |
| COMP-014 | All SDKs declared in store privacy labels / data safety forms | M | A | — | platforms includes ios/android |
| COMP-015 | Biometric data: written consent, retention schedule, storage rules | H | S | G | features.biometrics |
| COMP-016 | Emails: unsubscribe link, honest subject, physical address | H | S | E | features.email_sending |
| COMP-017 | Transactional vs marketing email separated; double opt-in for EU | M | S | G | features.email_sending |
| COMP-018 | No fake or placeholder testimonials, reviews, logos, or stats | H | S | E | |
| COMP-019 | GDPR: lawful basis documented; export and delete request flow; DPAs with processors; breach plan | H | S | G | |
| COMP-020 | CCPA/CPRA: Do Not Sell or Share link; Global Privacy Control honored | H | L | G | |
| COMP-021 | COPPA / age gating if minors may use the product | H | S | G | features.minors_possible |
| COMP-022 | PCI: card numbers never touch application servers | C | S | G | features.payments |
| COMP-023 | HIPAA / health-data handling and BAAs | C | A | — | features.health_data |
| COMP-024 | Other US state privacy laws; Washington MHMD if health-adjacent | M | A | — | |
| COMP-025 | TCPA consent for SMS | H | S | G | features.sms |
| COMP-026 | All fees, tax, and currency shown before checkout; refund policy stated | H | L | G | features.payments |
| COMP-027 | Legal name, address, and contact on site | M | L | E | |
| COMP-028 | Open-source, font, and image licenses complied with; attributions present | M | S | G | |
| COMP-029 | AI disclosure to users; chatbot transparency (EU AI Act) | M | S | G | features.ai |
| COMP-030 | Marketing claims substantiated: "free", comparative, health, results | M | S | G | |
| COMP-031 | Affiliate and sponsorship disclosures | L | S | E | |
| COMP-032 | Age of majority for contracts; beta/experimental disclaimers | L | S | E | |
| COMP-033 | B2B: DPA available to customers; subprocessor list published | M | A | G | features.b2b |
| COMP-034 | Trust and safety: report, block, moderation queue; legally required abuse reporting | H | S | G | features.user_content |
| COMP-035 | Terms acceptance recorded with version and timestamp | M | S | G | |
| COMP-036 | Privacy policy and terms linked from footer, sign-up, checkout, and store listings; reachable logged out | H | L | E | |

### 8.8 Mobile (MOB) — when platforms includes ios or android

| ID | Check | Sev | Tier | Fix |
|---|---|---|---|---|
| MOB-001 | Restore purchases works | C | L | G |
| MOB-002 | EULA linked in store listing | M | A | — |
| MOB-003 | OTA hotfix configured within store rules | M | S | G |
| MOB-004 | Privacy labels / data safety match actual SDKs | H | A | — |
| MOB-005 | Account deletion discoverable per store guidelines | H | L | G |
| MOB-006 | IAP rules followed for digital goods | H | S | G |
| MOB-007 | Permissions requested just-in-time with purpose strings; none unused | M | S | E |
| MOB-008 | Universal / app links verified (AASA, assetlinks) | M | R | G |
| MOB-009 | Push permission timing; token refresh; unsubscribe | M | S | G |
| MOB-010 | Release build tested; ATS not disabled; no cleartext traffic | H | S | E |
| MOB-011 | No extractable secrets in app bundle | C | S | G |
| MOB-012 | Force-update mechanism; version and build bumped | M | S | G |
| MOB-013 | Signing keys and keystore backed up | C | A | — |
| MOB-014 | Review demo account and notes provided | M | A | — |
| MOB-015 | Offline and poor-network handling | M | L | G |
| MOB-016 | Age rating, export compliance declaration, screenshots on all sizes | M | A | — |
| MOB-017 | Crash-free rate, app size, launch time acceptable | M | A | — |
| MOB-018 | Deep links into protected screens require auth | H | S | G |
| MOB-019 | Certificate pinning decision documented | L | A | — |
| MOB-020 | Apple privacy manifest present; required-reason APIs declared | H | S | E |
| MOB-021 | App Tracking Transparency prompt if tracking SDKs present | H | S | G |
| MOB-022 | Android targetSdk meets current Play requirement | H | S | E |
| MOB-023 | Sign in with Apple offered if other social logins are | H | S | G |

### 8.9 Flows (FLOW) — runtime walkthroughs, tier L, fix G unless noted

| ID | Check | Sev | when |
|---|---|---|---|
| FLOW-001 | Fresh sign-up end-to-end; verification email received | C | |
| FLOW-002 | Login, logout, session expiry behave | C | |
| FLOW-003 | Password reset end-to-end | C | |
| FLOW-004 | Test-mode checkout → webhook received → entitlement granted | C | features.payments |
| FLOW-005 | Cancel subscription → entitlement revoked at period end | H | features.subscriptions |
| FLOW-006 | Failed payment: decline, retry, notification, revocation | H | features.subscriptions |
| FLOW-007 | Trial reminder and conversion (simulated clock where possible) | H | features.trials |
| FLOW-008 | Restore purchases | H | platforms includes ios/android |
| FLOW-009 | Account deletion: rows gone, storage gone, login fails, emails stop | C | |
| FLOW-010 | Upload accepts valid file; rejects disguised executable | H | features.uploads |
| FLOW-011 | Data export request produces complete export | M | |
| FLOW-012 | Kill switch → maintenance response | H | |
| FLOW-013 | Consent declined → no analytics/pixel requests fire | H | |
| FLOW-014 | Unsubscribe link works | M | features.email_sending |
| FLOW-015 | Support contact reachable and lands with a human | M | |
| FLOW-016 | Empty states, 404, and error pages render | M | |
| FLOW-017 | Team invite and removal end-to-end | H | features.teams |
| FLOW-018 | Cross-browser and mobile-viewport smoke of primary flow | M | |
| FLOW-019 | Change email and password: re-auth required; notification to old address | H | |
| FLOW-020 | Social login end-to-end including same-email account linking | H | |
| FLOW-021 | Plan upgrade and downgrade with proration | H | features.subscriptions |

### 8.10 Payments (PAY) — when features.payments

| ID | Check | Sev | Tier | Fix |
|---|---|---|---|---|
| PAY-001 | Live webhook endpoint registered for prod URL with live signing secret | C | A | G |
| PAY-002 | Entitlement synced on every relevant event: failed, updated, cancelled, past_due, refund, dispute | C | S | G |
| PAY-003 | Webhook events deduplicated and order-tolerant; timestamp replay protection | H | S | G |
| PAY-004 | Idempotency keys on charge creation; double-submit cannot double charge | C | L | G |
| PAY-005 | Money stored as integer minor units with currency code | H | S | G |
| PAY-006 | Dunning: retry schedule, notification, grace period, revocation | H | S | G |
| PAY-007 | Plan limits enforced server-side; downgrade and proration defined | H | S | G |
| PAY-008 | Tax handled (Stripe Tax or equivalent); thresholds understood | H | A | G |
| PAY-009 | SCA / 3D Secure supported | H | S | G |
| PAY-010 | Receipts and invoices sent automatically and compliant | M | S | G |
| PAY-011 | Refund and dispute flow exists and is owned; fraud rules enabled | M | A | — |
| PAY-012 | Customer portal configured: cancel and card update work without support | H | L | G |
| PAY-013 | Restricted API keys used server-side where provider supports | M | S | E |
| PAY-014 | Pricing page, checkout, and terms state identical prices | H | L | E |
| PAY-015 | Promo and trial abuse limited: one trial per person; single-use codes | M | S | G |
| PAY-016 | Webhook delivery failure alerts configured at the provider | H | A | — |
| PAY-017 | Price change notice and consent for existing subscribers | H | S | G |
| PAY-018 | Entitlement granted only from webhook or server-verified session, never from success-URL params | C | S | G |

### 8.11 AI (AI) — when features.ai

| ID | Check | Sev | Tier | Fix |
|---|---|---|---|---|
| AI-001 | Retrieval respects user permissions; no cross-user document leakage | C | L | G |
| AI-002 | System prompt holds no secrets; leaking it exposes nothing sensitive | H | S | E |
| AI-003 | Prompt injection defenses for user content and retrieved documents; tools scoped to current user | H | S | G |
| AI-004 | Model output never executed, rendered as raw HTML, or used for authorization | C | S | G |
| AI-005 | Per-user and global spend caps; token limits per request; AI endpoints rate-limited | H | S | G |
| AI-006 | Timeouts, streaming cutoffs handled; fallback when provider is down | M | S | G |
| AI-007 | Provider retention/training opt-out configured; PII minimized in prompts and not logged in plaintext | H | A | G |
| AI-008 | Input and output moderation; self-harm and crisis handling with human escalation | C | S | G |
| AI-009 | Disclaimers for medical, legal, financial content; AI disclosure to users | M | S | G |
| AI-010 | Basic evals exist for core prompts | M | S | G |
| AI-011 | AI conversation history deletable by user; included in account deletion | H | S | G |
| AI-012 | Model version pinned; deprecation path known | M | S | E |

### 8.12 Hygiene (HYG)

| ID | Check | Sev | Tier | Fix |
|---|---|---|---|---|
| HYG-001 | Third-party dashboards configured for prod domain: OAuth redirect URIs, auth site URL and redirect allowlist, Apple Sign In, email sender domain, error tracker project, analytics property, backend CORS allowlist | C | A | G |
| HYG-002 | No hardcoded localhost or staging URLs in emails, OG tags, canonical, API base, or configs | H | S | E |
| HYG-003 | Placeholder content removed: lorem ipsum, default framework titles, sample data, "coming soon" stubs, staging banners; copy proofread | H | S | E |
| HYG-004 | No console logs, debug flags, TODO/FIXME in user-facing paths, or commented-out secrets | M | S | E |
| HYG-005 | No dead links, broken images, invalid contact emails, or broken social links; copyright year current | M | L | E |
| HYG-006 | Legal pages have effective dates and versions | M | S | E |
| HYG-007 | Repo hygiene: README with setup, LICENSE, no large binaries, no unused dependencies or dead routes | L | S | E |
| HYG-008 | Time bombs: hardcoded dates, expiring keys or trial licenses, lapsing free-tier limits | H | S | G |
| HYG-009 | Version bumped; changelog or release notes; launch commit tagged | L | S | E |
| HYG-010 | Browser matrix tested: Safari, iOS Safari, Chrome, Firefox, Edge | M | A | — |
| HYG-011 | Password managers work: autocomplete attributes correct; paste not blocked | L | S | E |
| HYG-012 | Forms preserve input on validation error; destructive actions confirm | L | L | E |
| HYG-013 | PWA/mobile-web basics: viewport meta, theme-color, manifest if installable, safe-area insets | L | S | E |
| HYG-014 | Internationalization sanity: dates, currency, and numbers formatted per locale; RTL if supported | L | S | E |
| HYG-015 | Production build succeeds from a clean clone with documented steps | H | L | G |
| HYG-016 | Email templates: absolute prod links, rendered across major clients, from-name set, reply-to monitored | H | L | E |

### 8.13 Access (ACC)

| ID | Check | Sev | Tier | Fix |
|---|---|---|---|---|
| ACC-001 | MFA enabled on GitHub, cloud console, payment provider, registrar, DNS, email provider, app stores | C | A | — |
| ACC-002 | More than one owner on every critical service; recovery codes stored in password manager | H | A | — |
| ACC-003 | No company service registered under a personal email | H | A | — |
| ACC-004 | Least-privilege service accounts; no shared logins; offboarding removes access | M | A | — |
| ACC-005 | Cloud root/owner account not used daily; cloud audit logging on | M | A | — |
| ACC-006 | Branch protection, required review, secret scanning, Actions pinned by SHA, Dependabot on | M | S | E |
| ACC-007 | Prod secrets in a secrets manager; rotation runbook for a leaked key | H | A | — |
| ACC-008 | Containers run non-root, minimal base image, no secrets in layers | M | S | E |
| ACC-009 | Domain: registrar lock, CAA records, no dangling CNAMEs | M | R | G |
| ACC-010 | security.txt and vulnerability disclosure contact | L | S | E |
| ACC-011 | Auto-renew on and valid payment method for registrar, hosting, database, email, error tracker | C | A | — |

Total: 317 checks across 13 domains. Payments, AI, and mobile run only when detected or configured.

## 9. Error handling

- Subagent crash: orchestrator reads whatever the domain wrote, marks unwritten checks `error: auditor did not complete`, and continues merging.
- Local env fails to start: report says which tier was unavailable and why; all `tier: local` checks degrade to static where a static verify exists, else `error`.
- Tool missing and declined: fallback verify or `error`, recorded in `verified_by`.
- Test account creation fails: FLOW-001 fails; all checks depending on the account become `error: no test account`.
- Fix re-verify fails: revert, `error`, continue. Never a partial fix.
- Report and findings are always written, even on a mostly-failed run.

## 10. Testing the skill

Evals live in `pre-launch/evals/evals.json` and run through the skill-creator loop. Initial test prompts, each against a small fixture repo:

1. **Next.js + Supabase + Stripe, deliberately broken.** Hardcoded Stripe key, webhook without verification, a table with RLS off, CORS `*`, no 404 page, no privacy policy. Expect: correct stack detection; SEC-001, SEC-051, DAT-001, SEC-035, SEO-009, COMP-001 all `fail`; report written; nothing modified.
2. **Same fixture, `/pre-launch fix security seo`, mode easy first.** Expect: SEC-035 and SEO-009 fixed and committed individually; SEC-051 presented but not applied without confirmation; SEC-001 handled as guided (rotation needed).
3. **Express + Prisma API only, no frontend, no local env.** Expect: static-only run; SEO and A11Y mostly `skipped` with reason; FLOW checks `error: local tier unavailable`; no crash.
4. **Re-run after fixes.** Expect: `first_seen` preserved, `resolved` set on fixed items, delta line correct.
5. **Scoped run `/pre-launch compliance`.** Expect: only COMP findings updated; other domains carried forward.

Assertions per eval are added during the eval loop.

## 11. Out of scope for v1

- Penetration-test-grade exploitation. The skill probes for presence of defenses, not full exploit chains.
- Generating legal documents from scratch. Drafts are suggestions for a lawyer, and the report says so.
- Automated app-store submission checks against live store consoles.
- CI integration. The skill is interactive; a headless mode can come later.
- Stacks beyond the listed set. Unknown stacks get generic static checks and a note.
