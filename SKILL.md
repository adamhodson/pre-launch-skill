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

If `PROJECT_DIR/.pre-launch/config.yml` exists, read it. Otherwise read `SKILL_DIR/references/config-format.md`, run its detection heuristics against the project, fill the schema, and show the result to the user with one question: "Here is what I detected. Correct anything wrong, or say go." Specifically call out the undetectable flags (`health_data`, `minors_possible`, `b2b`) and the local start command. Write the file.

Then, on every invocation of either phase and whether or not the config was just created: ensure `.pre-launch/` exists and that `.gitignore` contains a `.pre-launch/` line, creating `.gitignore` if the project has none. A config that already existed is exactly the case where the ignore line goes missing and the audit's own output shows up as untracked changes.

### 2. Applicable domains

Start from the requested domains (all if none named). Drop `mobile` unless `platforms` includes `ios` or `android`; drop `payments` unless `features.payments`; drop `ai` unless `features.ai`. Tell the user which domains will run and which were dropped and why; note that flows may also run once to create the test account even when not in scope.

### 3. Tiers

- `static`: always live.
- `local`: send `GET local.url + ready_path`. If it responds, do not treat local as live yet — first confirm the server answering that port belongs to **this** project. Run `lsof -nP -iTCP:<port> -sTCP:LISTEN` to get the listening PID and compare its working directory (`lsof -p <pid> | grep cwd`) against PROJECT_DIR; where that is inconclusive, fetch `/` and match its title or markup against this project's own pages. If it is another project's dev server, local is **not** live: say which process holds the port, never probe it, and do not start a second server on it. Otherwise local is live. If nothing responds and `local.start` is set, run it in the background and poll every 5 s until `ready_timeout_s`; live on 200, and the same ownership check applies. If it never responds, say so and continue with local not live.
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

Run the five stages below in order. The order exists because the shared test account must survive until performance has run, the non-destructive flow evidence must exist before the domains that reuse it, and FLOW-009 destroys the account, so it is last.

Read `SKILL_DIR/agents/domain-auditor.md` once before stage 1 and fill it per **Filling the template** below for every dispatch.

**Stage 1 — test account.** If `test_account.strategy` is `create` or `provided` and `local` is live, dispatch the flows subagent alone and tell it: "run only FLOW-001 and the empty-state half of FLOW-016; write `.pre-launch/findings/flows-1.json`; do not write `findings/flows.json`". FLOW-001 handles both strategies — it signs up under `create` and verifies a login under `provided` — and writes `PROJECT_DIR/.pre-launch/test-account.json`, which every account-dependent check reads. Run this stage even when `flows` is not in the requested scope. If `strategy` is `none`, or if `local` is not live, skip the stage: there is no account, and every account-dependent check records `error: no test account`.

**Stage 2 — the rest of flows.** Only if `flows` is in scope. Dispatch flows again: "run FLOW-002 through FLOW-021 except FLOW-009 and the parts already done in stage 1; write `.pre-launch/findings/flows.json`". This is the file every consuming check reads, which is why this stage owns the name and runs before the domains that cite flow evidence.

When stage 1 did **not** run — `test_account.strategy: none`, or `local` not live — stage 2's dispatch names FLOW-001 and FLOW-016 explicitly as well: "also run FLOW-001 and FLOW-016 from their `static` entries; there is no test account, so record what the code shows and `error` anything needing a live signup." Otherwise the two checks stage 1 owns vanish from the run without ever being reported.

**Stage 3 — everything else, in parallel.** Dispatch every applicable domain except `flows` and `performance`, all in the same turn. Each writes `PROJECT_DIR/.pre-launch/findings/<domain>.json`. Wait for all to finish. If the harness caps concurrent subagents (a dispatch is refused or queued), send the domains in batches of up to five, starting the next batch as slots free; the order within stage 3 does not matter.

**Stage 4 — performance.** Only if `performance` is in scope. Dispatch it alone. It generates load and measures a production build, so nothing may run beside it.

**Stage 5 — account teardown.** Only if `flows` is in scope. Dispatch flows a third time: "run only FLOW-009; write `.pre-launch/findings/flows-3.json`; do not write `findings/flows.json`". FLOW-009 deletes the shared account, which is why it is last.

FLOW-009's evidence cannot exist during the same full run for DAT-020, COMP-010, AI-011, MOB-005; those checks read FLOW-009 from a previous run's `findings.json` when present and otherwise take their disposable-account branch.

`merge_findings.py` globs `findings/*.json` in sorted order, so the three flows files merge by check ID like any other domain file and the later file wins on the same ID. `flows-1.json` < `flows-3.json` < `flows.json`, so stage 2's fuller FLOW-016 verdict still supersedes stage 1's.

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

Add these two lines to every dispatch: "a check file's header may override file order (flows, performance, and seo do); follow the header. If this dispatch names an output filename, it replaces the template's `findings/{{domain}}.json` — write only to the named file."

Each subagent's final line is a per-domain count. Collect them.

### 7. Merge

A subagent under a time budget can drop a check without noticing — a run once returned 19 of 20 flow IDs — so gate the merge on coverage first:

    python3 SKILL_DIR/scripts/check_coverage.py --dir PROJECT_DIR/.pre-launch --domains <comma-separated domains that ran>

It prints `complete` or `missing <IDs>` per domain and exits 1 on any gap. For each domain with gaps, dispatch that domain once more with "run only <IDs>; write `.pre-launch/findings/<domain>-2.json`", then re-run the gate. A check the config skips or a `when` clause rules out still counts as covered, because the template records it as `skipped`; only an ID that appears nowhere is a gap. Merge only when every domain is complete.

Then run:

    python3 SKILL_DIR/scripts/merge_findings.py --dir PROJECT_DIR/.pre-launch --domains <comma-separated domains that ran> --tiers <comma-separated live tiers>

`--domains` is every domain that produced a findings file, so include `flows` whenever stage 1 ran even if flows was not in the requested scope. Then delete `PROJECT_DIR/.pre-launch/findings/`.

### 8. Summary

Read `PROJECT_DIR/.pre-launch/findings.json` for the numbers below — `report.md` is the artifact you point the user at, not the source you count from. Print:

- the delta line (resolved / new / regressed / open), as the merger printed it. When the previous run's `domains` list in `runs` is shorter than this run's, the "new" count is mostly scope growth rather than regression, so print directly after it: "N new includes checks run for the first time; compare like-for-like domains for regressions.";
- the blocker count as the report's `Blockers (critical, open)` line gives it (critical `fail` findings), plus, separately, the count of critical-severity `attest` findings — gaps a human must confirm rather than defects (SEC-060, ACC-001, ACC-011, HYG-001, PAY-001 are examples);
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

`/pre-launch fix [domains...]`

### 1. Load

Read `PROJECT_DIR/.pre-launch/findings.json`. If it is missing, stop: "No findings yet. Run `/pre-launch` first." Apply the `.gitignore` rule from audit step 1 here too, before any commit. Compare the newest commit in the project against the `at` of the newest run in `runs` whose `domains` is not `["none"]` — that is the last real audit; the fix phase's own merger calls stamp runs with `domains: none` and would otherwise look like a fresh audit. If the commit is later, say the findings may be stale and continue.

Then apply any attestation boxes the user ticked in `report.md`:

    python3 SKILL_DIR/scripts/merge_findings.py --dir PROJECT_DIR/.pre-launch --domains none --tiers none

The `findings/` directory does not have to exist. The script globs it, finds no domain files, merges nothing new, flips every carried-forward `attest` finding whose box is ticked to `status: pass` / `verified_by: attested`, rewrites `findings.json` and `report.md`, and prints the delta line. Re-read `findings.json` afterwards and work from that copy.

Then run `git status --porcelain` once. If the project already has uncommitted changes, say so — "the working tree already has changes; each fix commit will stage only the files that fix touches" — and continue. Never stash, reset, or check out anything you did not write yourself. If the project is not a git repo, warn once and run the whole phase without commits.

### 2. Queue

Select findings with `status: fail` in the scoped domains — no domain arguments means all domains. Split into **easy** (`fix: easy`) and **guided** (`fix: guided`); `fix: none` findings are not fixable here — list their IDs once and leave them alone. Print counts by group and severity, then ask one question:

> How do you want to work through these?
> 1. **All** — fix every easy finding without stopping, then walk the guided ones with me.
> 2. **Easy first** — same, but pause after the easy batch so you can review before the guided walk.
> 3. **One by one** — confirm every change, including easy ones.

Ordering within a group: critical, high, medium, low, then by ID.

### 3. Easy loop (modes 1 and 2; in mode 3 every finding goes through step 4 instead)

For each easy finding:

1. Read its block in `SKILL_DIR/references/checks/<domain>.md` and the stack headings its `fix_hint` names.
2. Make the smallest change that satisfies the check. Do not refactor around it.
3. Re-verify. Run the check's `verify` entry for the tier recorded in the finding's `verified_by`: `static`, `local`, or `remote` run that entry; `static-fallback` runs the `static` entry. When the finding's `verified_by` is `static` or `static-fallback` but the check's own `tier` is `local` or `remote`, the static entry can only show the fix is present in code, not that it behaves — commit on that basis, since it is the same evidence the audit accepted, but add `notes: "re-verified statically; runtime behaviour confirmed by the next audit with <tier> live"` so the report does not overstate it. If the tier is `local` and the server is not running, bring it up the way the audit phase does — `local.start` from the config normally, or a production build (`npm run build && PORT=<port> npm start` with `NODE_ENV=production`, or this stack's equivalent per the stack reference's "build" heading) when the check measures response headers, compression, or rendered markup, which is the rule the performance and SEO check-file headers state. Stop anything you started once the loop finishes, not between findings.
4. **Verify passes:** stage only the files this fix touched — `git add <files>`, never `git add -A` — and commit `fix(<ID>): <title>`. No trailers; this is the user's project, not the skill's repo. Then set `status: pass`, `verified_by` unchanged, `resolved: <now>`, `commit: <sha>` in `findings.json`.
5. **Verify fails:** revert the fix before moving on — `git checkout -- <the files you touched>` and delete any file you created — then set `status: error` and `notes: "fix attempted; re-verify failed: <reason>"` and continue. Never carry a half-applied fix into the next finding.
6. **Tier cannot be brought up** (the server will not start, the production build fails, `remote.url` is unreachable): an unverified fix is never committed. Revert exactly as in step 5 — `git checkout -- <the files you touched>`, delete any file you created — and leave `status: fail`, `resolved: null`, no `commit`, and `notes: "fix deferred; re-verify needs <tier> — bring it up and re-run /pre-launch fix"`.

After the batch print a table: ID, title, result. In mode 2, first re-run the merger so the artifact the user is about to review matches what just happened —

    python3 SKILL_DIR/scripts/merge_findings.py --dir PROJECT_DIR/.pre-launch --domains none --tiers none

— then stop and wait for the user to say continue. (Ignore the delta line it prints, for the reason step 5 gives.)

### 4. Guided loop

For each guided finding, show ID, title, severity, evidence, recommendation, and a concrete proposal — a diff for code changes, a written plan for config, DNS, or dashboard changes you cannot make yourself. Ask: **yes / edit / skip**.

- **yes** — apply it, then re-verify, commit, and update the finding exactly as steps 3.3 through 3.6 describe. When the proposal was a plan you cannot carry out yourself, there is nothing to commit: leave `status: fail` and put what the user has to do in `notes`, and say the next `/pre-launch` will confirm it.
- **edit** — take the user's changes and re-propose. Nothing is applied until they say yes.
- **skip** — leave `status: fail` and record any reason the user gives in `notes`.

Legal-text findings are never edited in place: **COMP-001, COMP-002, COMP-003, COMP-004, COMP-005, COMP-009, COMP-012, COMP-016, COMP-029, COMP-030.** For these, write a draft to `PROJECT_DIR/.pre-launch/drafts/<ID>.md` (create the directory if needed) containing the proposed text, the evidence from the finding that drove each part of it — the SDK, the data flow, the pricing page, the file:line — and the line "Not legal advice; review with counsel." Tell the user where the draft is, and leave the finding `status: fail` until they confirm the text is published.

### 5. Wrap

Re-run the merger command from step 1 to regenerate `report.md` from your edited `findings.json`. Ignore the delta line it prints and never quote it here: that delta counts only findings merged from domain files, and this call merges none, so it always reads 0 resolved.

Report your own tally instead, kept as you went through the loops:

> This session: N fixed and committed, N deferred (tier unavailable), N failed re-verify, N skipped, N guided remaining, N attest remaining.

Then print the report path, and list the IDs of the guided findings still open and the `attest` findings still unticked. Recommend a full `/pre-launch` once that list is clear, because fixes shift other findings.

### What the fix phase never does

- Never changes a finding whose status is `attest`. Those are the user's to tick in `report.md`; the merger applies the ticks.
- Never touches a finding outside the scoped domains, even when the fix is obvious and one line.
- Never leaves a partially applied fix and never commits one whose verify did not run and pass: a failed re-verify and a tier that will not come up are both reverted.
- Never puts two findings in one commit, and never runs `git add -A`, `git stash`, or `git reset`.
- Never auto-applies a guided finding, in any mode.
- Never edits `PROJECT_DIR/.pre-launch/config.yml` or any file under `SKILL_DIR/references/checks/`. The config is the audit's input and the check files are the skill's; a fix that seems to need either is a finding to report, not a file to change.
