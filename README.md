# pre-launch

A Claude Code skill that audits a web or mobile app before it ships to production, then fixes what the audit finds.

Run it from the root of a project. It detects the stack, runs 317 checks across 13 domains using the codebase, a local dev server, and optionally a staging URL, and writes a report with evidence for every verdict. When you are ready, a second phase walks the findings and repairs them, one commit per fix, re-verifying each one before it is committed.

## Contents

- [Quick start](#quick-start)
- [Installation](#installation)
- [Commands](#commands)
- [What gets checked](#what-gets-checked)
- [How the audit works](#how-the-audit-works)
- [The fix phase](#the-fix-phase)
- [Configuration](#configuration)
- [Output files](#output-files)
- [Verdicts and tiers](#verdicts-and-tiers)
- [Safety guarantees](#safety-guarantees)
- [Supported stacks](#supported-stacks)
- [Tools it can use](#tools-it-can-use)
- [Repository layout](#repository-layout)
- [Development](#development)
- [Evaluation results](#evaluation-results)
- [Known limitations](#known-limitations)

## Quick start

```
cd your-project
/pre-launch
```

The skill detects your stack, shows you the config it inferred, and asks one question before running. When it finishes it prints a delta line, the blocker count, the top open findings, and the path to `.pre-launch/report.md`.

Read the report. Tick the attestation boxes for anything you can vouch for. Then:

```
/pre-launch fix
```

It asks how you want to work through the findings, fixes the easy ones with a commit per finding, and walks you through the guided ones with a concrete proposal each time.

## Installation

Clone this repository into your Claude Code skills directory:

```
git clone git@github.com:adamhodson/pre-launch-skill.git ~/.claude/skills/pre-launch
```

Or install the packaged `.skill` file from a release. Python 3 is required for the bundled scripts; nothing else is installed without asking.

The skill triggers on `/pre-launch` and on natural-language requests such as "are we ready to launch", "what will bite us in prod", "production readiness review", or "go-live checklist for this code". It also triggers when you ask to re-run a previous audit and see what changed.

## Commands

| Invocation | Action |
|---|---|
| `/pre-launch` | audit every applicable domain |
| `/pre-launch security data` | audit only the named domains |
| `/pre-launch fix` | fix phase over all domains |
| `/pre-launch fix seo hygiene` | fix phase scoped to named domains |
| `/pre-launch config` | re-run stack detection, show a diff against the existing config, ask before overwriting |

Domain names: `security data performance reliability seo accessibility compliance mobile flows payments ai hygiene access`.

Domains that do not apply are dropped automatically and the skill tells you why: `mobile` needs an iOS or Android platform, `payments` needs `features.payments`, and `ai` needs `features.ai` in the config.

## What gets checked

317 checks across 13 domains. Each check has a stable ID, a severity, a verification tier, and a fix classification.

| Domain | ID prefix | Checks | What it covers |
|---|---|---|---|
| Security | SEC | 67 | secrets, headers, auth, sessions, CORS, injection, webhooks, dependencies, rate limiting, upload handling, admin surfaces |
| Data | DAT | 27 | row-level security, policies, backups, migrations, PII handling, retention, deletion, encryption at rest |
| Performance | PERF | 20 | Core Web Vitals, bundle size, caching, compression, images, N+1 queries, load testing against the local build, cold starts |
| Reliability | REL | 31 | health checks, error tracking, logging, alerting, timeouts, retries, idempotency, kill switch, rollback, DNS and TLS |
| SEO | SEO | 17 | titles, meta, canonical, sitemap, robots, structured data, 404 handling, redirects, broken links, Open Graph |
| Accessibility | A11Y | 18 | axe scan, keyboard navigation, focus, contrast, labels, headings, reduced motion, screen-reader landmarks |
| Compliance | COMP | 36 | privacy policy, terms, cookie consent, data subject rights, account deletion, GDPR and CCPA, email compliance, age gating |
| Mobile | MOB | 23 | store listing, permissions, privacy manifests, deep links, push, crash reporting, OTA updates, kill switch, IAP |
| Flows | FLOW | 21 | sign-up, login, password reset, checkout, subscription lifecycle, account deletion, empty states, exercised end to end |
| Payments | PAY | 18 | webhook signatures, idempotency, test-mode keys, tax, dunning, refunds, entitlement sync, price integrity |
| AI | AI | 12 | prompt injection, output handling, cost controls, rate limits, data sent to providers, disclosure |
| Hygiene | HYG | 16 | leftover scaffolding, console output, TODOs, README accuracy, clean-clone build, email templates, licence |
| Access | ACC | 11 | who holds the keys: domain registrar, DNS, cloud, app stores, payment dashboards, break-glass procedures |

The full inventory with severities and tiers is in `docs/superpowers/specs/2026-09-03-pre-launch-skill-design.md`, section 8. Each check's procedure lives in `references/checks/<domain>.md`.

### Check anatomy

Every check block has the same fields:

```
### SEC-051 Webhook signature verification on every webhook handler
severity: critical
tier: local
fix: guided
when: features.payments
why: ...
verify:
  static: ...
  local: ...
  remote: ...
  attest: ...
evidence: ...
fix_hint: ...
```

- `tier` is the highest tier at which the check can be proven. The auditor uses the highest tier that is live.
- `fix` is `easy` (mechanical, applied automatically in the fix phase), `guided` (needs your approval and a proposal), or `none` (not fixable from code).
- `when` gates the check on a config feature flag. Gated-out checks are recorded as `skipped` with the reason, never dropped silently.

## How the audit works

The orchestrator in `SKILL.md` runs nine steps.

1. **Config.** Reads `.pre-launch/config.yml` or runs detection heuristics against the project and asks you to confirm. Every run also ensures `.gitignore` contains a `.pre-launch/` line.
2. **Applicable domains.** Resolves the requested scope against platforms and feature flags.
3. **Tiers.** `static` is always live. `local` is live if the configured URL answers or the start command brings it up. `remote` is live if the staging URL responds. Before using a port that already answers, the skill checks that the listening process belongs to this project. A server from another project is never probed.
4. **Tools.** Checks for optional tools and asks once before installing any. Refusals are remembered in the config.
5. **Dispatch.** Runs domain auditors as subagents in five stages. Stage 1 creates or verifies the shared test account. Stage 2 exercises the non-destructive user flows, since other domains cite that evidence. Stage 3 runs every remaining domain in parallel, in batches if the harness caps concurrency. Stage 4 runs performance alone because it generates load. Stage 5 deletes the test account, which is why it is last.
6. **Filling the template.** Each subagent receives `agents/domain-auditor.md` with its check file, the stack references for the detected stacks, the config, the live tiers, and the previous run's findings for that domain.
7. **Coverage gate and merge.** `scripts/check_coverage.py` confirms every check ID in each dispatched domain was recorded; gaps are re-dispatched. Then `scripts/merge_findings.py` merges the domain files into `findings.json`, carries forward history, applies ticked attestations, and renders `report.md`.
8. **Summary.** Prints the delta line, blocker count, critical attestations, the top five open findings, and the report path.
9. **Cleanup.** Stops any server the skill started and reports whether the test account still exists.

Each domain auditor works through its check file in order, picks the tier, gathers evidence, and records one finding per check ID. A check with no evidence is never a pass. Measurement checks with no live tier record `error`, never a predicted pass. Domain files are written atomically so parallel auditors can read each other's evidence safely.

## The fix phase

`/pre-launch fix [domains...]` reads `findings.json` back and repairs `fail` findings.

**Load.** Applies any attestation boxes you ticked in the report, warns if the project has commits newer than the last audit, and warns if the working tree already has changes. It never stashes, resets, or checks out anything it did not write.

**Queue.** Splits findings into easy and guided and asks one question:

1. **All**: fix every easy finding without stopping, then walk the guided ones with you.
2. **Easy first**: same, but pause after the easy batch so you can review before the guided walk. The report is regenerated at the pause.
3. **One by one**: confirm every change, including easy ones.

**Easy loop.** For each finding: make the smallest change that satisfies the check, re-run the check's verify entry at the tier the audit used, and only then stage the touched files and commit as `fix(<ID>): <title>`. A failed re-verify is reverted and recorded. A fix whose re-verify needs a tier that cannot be brought up is reverted and deferred with a note, never committed unverified.

**Guided loop.** For each finding you see the evidence, the recommendation, and a concrete proposal, which is a diff for code or a written plan for DNS, dashboards, and config you must change yourself. Answer yes, edit, or skip. Nothing is applied until you say yes.

**Legal text is never edited in place.** For privacy policy, terms, cookie, and similar findings the skill writes a draft to `.pre-launch/drafts/<ID>.md` with the evidence that drove each clause and the line "Not legal advice; review with counsel." The finding stays open until you confirm the text is published.

**Wrap.** Regenerates the report and prints a session tally: fixed, deferred, failed re-verify, skipped, guided remaining, attest remaining. It recommends a full re-audit once the list is clear, because fixes shift other findings.

## Configuration

`.pre-launch/config.yml` is created on the first run from detection heuristics and is yours to edit afterwards.

```yaml
version: 1
stacks: [nextjs, supabase, stripe, vercel]
platforms: [web]                  # web | ios | android
local:
  url: http://localhost:3000
  start: npm run dev              # null = you start it yourself
  ready_path: /
  ready_timeout_s: 120
remote:
  url: null                       # staging or preview URL, optional
test_account:
  strategy: create                # create | provided | none
  email_pattern: prelaunch+{ts}@example.com
  email: null                     # used when strategy: provided
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
skip:
  - id: SEO-005
    reason: internal tool, not indexed
```

Three flags cannot be detected from code and are called out explicitly on the first run: `health_data`, `minors_possible`, and `b2b`. They gate compliance checks, so answer them honestly.

`skip` is for checks you have consciously waived. The reason appears in the report so the decision is visible.

`test_account.strategy` matters for the flows domain. With `create`, the skill signs up a throwaway account using the email pattern. With `provided`, it logs in with your account and never deletes it. With `none`, every account-dependent check records `error: no test account`.

Detection heuristics and the full schema are in `references/config-format.md`.

## Output files

Everything the skill writes lives under `.pre-launch/`, which it adds to `.gitignore`.

| File | Purpose |
|---|---|
| `config.yml` | detected and confirmed configuration |
| `findings.json` | machine-readable findings with run history |
| `report.md` | human-readable report grouped by domain, with attestation checkboxes |
| `test-account.json` | the shared test account created for the run, with a `deleted` flag |
| `drafts/<ID>.md` | proposed legal text from the fix phase |
| `<domain>/` | evidence artifacts a domain auditor saved, such as logs and probe output |

`findings.json` holds one object per check ID:

```json
{
  "id": "SEC-001",
  "title": "No hardcoded secrets or API keys in source",
  "domain": "security",
  "severity": "critical",
  "status": "fail",
  "fix": "easy",
  "evidence": "app/api/webhooks/stripe/route.ts:2 — sk_live_ literal",
  "recommendation": "Move the Stripe secret key to an environment variable and rotate the exposed key.",
  "verified_by": "static",
  "first_seen": "2026-09-03T12:00:00Z",
  "last_checked": "2026-09-04T09:12:00Z",
  "resolved": null,
  "commit": null,
  "notes": ""
}
```

Runs accumulate in a `runs` array, so the merger can print a delta each time: resolved, new, regressed, open. When a run covers more domains than the previous one, the summary says so, because most of the "new" count is scope growth rather than regression.

The report format is specified in `references/report-format.md`.

## Verdicts and tiers

Each finding has a status:

| Status | Meaning |
|---|---|
| `pass` | the defence or behaviour was observed |
| `fail` | its absence or a bad response was observed |
| `attest` | machinery exists but only a human can confirm the process; tick the box in the report |
| `skipped` | gated out by a feature flag or listed in `skip`, with the reason |
| `error` | the check could not be completed, with the reason |

`verified_by` records the tier actually used: `static`, `local`, `remote`, `attest`, `attested` (after you tick the box), or `static-fallback` when a preferred tool was unavailable. A static fallback can pass only when inspection alone proves the property. It never substitutes for a measurement or a runtime probe.

The summary always says which tiers were not live, so you know which `error` and `attest` entries are environment gaps rather than defects.

## Safety guarantees

The audit phase:

- never edits, creates, or deletes project files outside `.pre-launch/` and the one `.gitignore` line;
- never runs load tests against the remote URL;
- never probes a server on the configured port that belongs to another project;
- uses only the test account and test-mode keys for any probe that could mutate data, and records `error` instead when test-mode keys cannot be confirmed;
- runs installs and builds only inside a throwaway clone under `.pre-launch/`, never in the project tree.

The fix phase:

- never changes a finding whose status is `attest`;
- never touches a finding outside the scoped domains, even for a one-line fix;
- never leaves a partially applied fix and never commits one whose re-verify did not run and pass;
- never puts two findings in one commit, and never runs `git add -A`, `git stash`, or `git reset`;
- never auto-applies a guided finding in any mode;
- never edits the config or the skill's own check files.

## Supported stacks

Stack references under `references/stacks/` tell auditors where to look for routes, auth, webhooks, data access, uploads, jobs, logging, headers, build commands, environment variables, and known traps. A configured stack without a reference falls back to generic search and the summary says so.

| Category | Stacks |
|---|---|
| Web frameworks | Next.js, Nuxt, SvelteKit, Remix, Astro |
| Backends | Express, FastAPI, Django, Rails, Laravel |
| Data | Supabase, Firebase, Prisma, Drizzle |
| Payments | Stripe, RevenueCat, Lemon Squeezy |
| Mobile | Expo, React Native, Flutter |
| Hosting | Vercel, Netlify, Cloudflare, Fly |

## Tools it can use

The skill asks once before installing anything and remembers refusals. Every domain has a documented fallback when a tool is missing.

| Tool | Used by |
|---|---|
| gitleaks | security |
| npm audit, pip-audit, bundler-audit, composer audit | security |
| lighthouse | performance, accessibility, seo |
| @axe-core/cli | accessibility |
| autocannon or k6 | performance |
| dig | reliability, access |
| stripe CLI | flows, payments |

Everything else uses `curl`, `grep`, `git`, the project's own package manager, and Python's standard library.

## Repository layout

```
SKILL.md                         orchestrator: audit and fix phases
agents/domain-auditor.md         subagent template, filled per domain
references/
  checks/<domain>.md             317 check blocks across 13 files
  stacks/<stack>.md              24 stack references with 15 fixed headings
  config-format.md               config schema and detection heuristics
  report-format.md               findings.json and report.md contracts
scripts/
  merge_findings.py              merge domain files, carry history, render the report
  check_coverage.py              coverage gate run before the merge
  probe_url.py                   HTTP probe helper for SEO and header checks
  validate_checks.py             dev-time linter for check and stack files
tests/                           pytest suite for the scripts
evals/                           eval prompts, assertions, and fixture projects
docs/                            design spec, implementation plan, original checklist
```

## Development

Run the tests and the check-file linter before committing changes to references or scripts:

```
python3 -m pytest tests -q
python3 scripts/validate_checks.py
```

The linter verifies that every check block matches the spec inventory, has the required fields in order, and that stack files carry all 15 headings.

### Adding a check

1. Add the row to the domain's table in the spec under section 8.
2. Add the block to `references/checks/<domain>.md` with all fields, one line per verify tier.
3. Run the linter.

Findings keep their history by ID, so never renumber an existing check.

### Evals

`evals/evals.json` holds five scenarios with assertions: a static audit of a broken Next.js app, a fix run in easy-first mode, an API-only Express project with no local tier, a re-run delta after two fixes, and a scoped compliance run. Fixture projects live under `evals/fixtures/`. The fixtures contain deliberate defects, including a placeholder Stripe key that is not a real credential.

The evals were run with the skill-creator plugin's eval loop; see [Evaluation results](#evaluation-results).

### Packaging

```
python -m scripts.package_skill <path-to-this-repo> dist/
```

from the skill-creator plugin directory produces `dist/pre-launch.skill`. Package from a clean checkout so editor and cache directories are not included.

## Evaluation results

Three iterations of the eval loop, five scenarios each, with-skill runs compared against Claude working from the same prompt with no skill.

| Iteration | With skill | Without skill | Notes |
|---|---|---|---|
| 1 | 96% | 88% | assertions too loose to discriminate |
| 2 | 95% | 74% | assertions tightened; merger and measurement fixes |
| 3 | 100% | 74% | coverage gate, batched dispatch, atomic writes |

With-skill runs take 20 to 30 minutes and roughly 100k tokens for a full audit because they dispatch 10 to 11 domain auditors and record every check ID. The baseline finishes in under four minutes and finds a handful of headline defects with no stable IDs, no attestation list, no per-finding commits, and no honest tier handling.

The trigger description was tuned with 20 realistic queries: 8 of 10 should-trigger queries invoke the skill and none of the 10 near-miss queries do.

## Known limitations

- The audit is only as complete as the live tiers. With no local server, every runtime measurement records `error`. Bring the local build up before relying on the performance, flows, or accessibility verdicts.
- Attestation items are gaps a human must confirm. A report with all boxes unticked is not a passing report.
- Mobile checks that need a device or a store dashboard record `attest` with the machinery found.
- A full audit is slow by design. Use a scoped run for a quick pass over one domain.
- Re-running an audit right after fixes will show a large "new" count when the scope grew. Compare like-for-like domains for regressions.
