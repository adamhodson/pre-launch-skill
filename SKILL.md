---
name: pre-launch
description: Audit a web or mobile app project before it ships to production and then fix what the audit finds. Runs 317 checks across security, data, payments, flows, reliability, performance, compliance, access, AI, mobile, accessibility, SEO, and launch hygiene, using the codebase, a local dev server, and optionally a staging URL. Use this whenever the user says pre-launch, launch checklist, go-live, production readiness, ship checklist, security audit before launch, "are we ready to launch", "what am I missing before release", or asks to review a project for launch, even if they only mention one area like SEO or compliance. Also use for `/pre-launch fix` to work through the findings report.
---

# Pre-Launch

Two phases. **Audit** writes `.pre-launch/findings.json` and `.pre-launch/report.md` and never touches project code. **Fix** reads them back and repairs findings with per-finding commits. Both run from the project root.

Skill directory: the directory containing this file; call it `SKILL_DIR` below. Project directory: the current working directory; call it `PROJECT_DIR`.

## Arguments

| Invocation | Action |
|---|---|
| `/pre-launch` | audit all applicable domains |
| `/pre-launch security data` | audit only the named domains |
| `/pre-launch fix` | fix phase over all domains |
| `/pre-launch fix seo hygiene` | fix phase scoped to named domains |
| `/pre-launch config` | re-run detection, show a diff against the existing config, ask before overwriting |

Domain names: `security data performance reliability seo accessibility compliance mobile flows payments ai hygiene access`. Unknown names stop with a message listing valid ones.

## Audit phase

### 1. Config

If `PROJECT_DIR/.pre-launch/config.yml` exists, read it. Otherwise read `SKILL_DIR/references/config-format.md`, run its detection heuristics against the project, fill the schema, and show the result to the user with one question: "Here is what I detected. Correct anything wrong, or say go." Specifically call out the undetectable flags (`health_data`, `minors_possible`, `b2b`) and the local start command. Write the file, create `.pre-launch/` and add it to `.gitignore` if not present.

### 2. Applicable domains

Start from the requested domains (all if none named). Drop `mobile` unless `platforms` includes `ios` or `android`; drop `payments` unless `features.payments`; drop `ai` unless `features.ai`. Tell the user which domains will run and which were dropped and why.

### 3. Tiers

- `static`: always live.
- `local`: send `GET local.url + ready_path`. If it responds, live. Otherwise, if `local.start` is set, run it in the background and poll every 5 s until `ready_timeout_s`; live on 200. If it never responds, say so and continue with local not live.
- `remote`: if `remote.url` is set, one `HEAD` request; live on any HTTP response.

Record the live tiers. Load testing (performance domain) only ever targets `local.url`.

### 4. Tools

For the domains that will run, check presence with `command -v` or `npx --no-install <tool> --version`:

| Tool | Needed by |
|---|---|
| gitleaks | security |
| npm audit / pip-audit / bundler-audit / composer audit (whichever matches the stack) | security |
| lighthouse (`npx lighthouse`) | performance, accessibility, seo |
| @axe-core/cli | accessibility |
| autocannon or k6 | performance |
| dig | reliability, access |
| stripe CLI | flows, payments (only if stripe is a stack) |

Skip anything listed in `tools.declined`. Ask once: "These tools are missing: X, Y. Install them? (yes / no / pick)". Install what is approved (`brew install`, `npm i -g`, or `pipx install` as appropriate for the tool and platform). Add refusals to `tools.declined` in the config. Domains fall back per their check files.

### 5. Dispatch order

Run the five stages below in order. The order exists because the shared test account must survive until performance has run, flows must not run after a load has throttled the app, and FLOW-009 destroys the account.

Read `SKILL_DIR/agents/domain-auditor.md` once before stage 1 and fill it per **Filling the template** below for every dispatch.

**Stage 1 — test account.** If `test_account.strategy` is `create` and `local` is live, dispatch the flows subagent alone and tell it: "run only FLOW-001 and the empty-state half of FLOW-016; write `.pre-launch/findings/flows-1.json`". It writes `PROJECT_DIR/.pre-launch/test-account.json`, which every account-dependent check reads. Run this stage even when `flows` is not in the requested scope. If `strategy` is `provided`, write `test-account.json` yourself from the config values (`{"email": ..., "password_env": <credentials_env>, "user_id": null, "created_at": <now>, "cookie": null}`) and skip this dispatch. If `strategy` is `none`, or if it is `create` but `local` is not live, skip the stage: there is no account, and every account-dependent check records `error: no test account`.

**Stage 2 — everything else, in parallel.** Dispatch every applicable domain except `flows` and `performance`, all in the same turn. Each writes `PROJECT_DIR/.pre-launch/findings/<domain>.json`. Wait for all to finish.

**Stage 3 — the rest of flows.** Only if `flows` is in scope. Dispatch flows again: "run FLOW-002 through FLOW-021 except FLOW-009 and the parts already done in stage 1; write `.pre-launch/findings/flows-2.json`".

**Stage 4 — performance.** Only if `performance` is in scope. Dispatch it alone. It generates load and measures a production build, so nothing may run beside it.

**Stage 5 — account teardown.** Only if `flows` is in scope. Dispatch flows a third time: "run only FLOW-009; write `.pre-launch/findings/flows-3.json`". FLOW-009 deletes the shared account, which is why it is last.

`merge_findings.py` globs `findings/*.json`, so the three flows files merge by check ID like any other domain file.

### 6. Filling the template

Substitute into `SKILL_DIR/agents/domain-auditor.md`:

- `{{domain}}`: the domain name.
- `{{check_file}}`: `SKILL_DIR/references/checks/<domain>.md`.
- `{{stack_files}}`: `SKILL_DIR/references/stacks/<stack>.md` for every stack in config that has a file under `SKILL_DIR/references/stacks/`. If a configured stack has no file, say so in the dispatch — "no stack reference for X; use generic search" — and note it in the summary you print in step 8.
- `{{config}}`: `PROJECT_DIR/.pre-launch/config.yml`.
- `{{tiers}}`: the live tiers from step 3.
- `{{test_account_path}}`: `PROJECT_DIR/.pre-launch/test-account.json`.
- `{{previous_findings}}`: the JSON array of this domain's findings from the existing `PROJECT_DIR/.pre-launch/findings.json`, or the literal `none` when there is no previous run.
- `{{budget_minutes}}`: `budget_minutes_per_domain` from config, default 20.
- `{{skill_dir}}`: `SKILL_DIR`. `{{project_dir}}`: `PROJECT_DIR`.

Add one line to every dispatch: "a check file's header may override file order (flows and performance do); follow the header."

Each subagent's final line is a per-domain count. Collect them.

### 7. Merge

Run:

    python3 SKILL_DIR/scripts/merge_findings.py --dir PROJECT_DIR/.pre-launch --domains <comma-separated domains that ran> --tiers <comma-separated live tiers>

`--domains` is every domain that produced a findings file, so include `flows` whenever stage 1 ran even if flows was not in the requested scope. Then delete `PROJECT_DIR/.pre-launch/findings/`.

### 8. Summary

Read the first 30 lines of `PROJECT_DIR/.pre-launch/report.md` and print to the user:

- the delta line (resolved / new / regressed / open);
- the blocker count — `fail` findings, counted separately from critical-severity `attest` findings, which are gaps a human must confirm rather than defects (SEC-060, ACC-001, ACC-011, HYG-001, PAY-001 are examples);
- the top five open findings by severity;
- any configured stack that had no reference file;
- the report path.

Say plainly which tiers were not live and that those checks show as `error` or `attest`. Do not summarize the whole report in chat; the report is the artifact. Point to it.

### 9. Cleanup

If the skill started the dev server, stop it. If the skill created the test account and `test-account.json` does not say `deleted: true`, say the account still exists and how to remove it (or that FLOW-009 in a later run will).

### Rules for the audit phase

- Never edit, create, or delete project files outside `.pre-launch/` and the `.gitignore` line.
- Never run load tests against `remote.url`.
- If a subagent fails outright, note it, mark its checks `error: auditor did not complete` by writing a domain file with those entries before merging, and continue.

## Fix phase
