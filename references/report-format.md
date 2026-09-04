# Report format

## findings.json

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

## Merge rules

- Match on `id`. Preserve `first_seen` from previous. Set `last_checked` to now.
- `fail` → `pass` sets `resolved` to now. `pass` → `fail` clears `resolved` and appends "regressed" to `notes`.
- Findings for domains not in this run are carried forward unchanged.
- Attestation boxes ticked in `report.md` are read before merge and set `status: pass`, `verified_by: attested`.

## report.md

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

## Per-domain findings files

Each domain subagent writes `.pre-launch/findings/<domain>.json`: a JSON array of finding objects with every field present (`null` where unknown). `first_seen`, `last_checked`, `resolved`, and `commit` are always `null` in domain files; the merger owns them. Write the file after each check completes (rewrite the whole array) so a crash keeps prior results.

## Merging

Run from the project root after all subagents finish:

    python3 <skill-dir>/scripts/merge_findings.py --dir .pre-launch --domains <comma list> --tiers <comma list>

It reads `.pre-launch/findings/*.json`, previous `findings.json`, and ticked boxes in `report.md`; writes both files; prints the delta line. Delete `.pre-launch/findings/` afterwards so a later scoped run does not re-merge stale domain files.

Ticked attestation boxes are applied to carried-forward findings too — an `attest` finding not re-checked this run still flips to `status: pass`, `verified_by: attested` if its box is ticked. This means running the merger with no `findings/` directory present (`--domains none --tiers none`) is how the fix phase applies ticks and re-renders the report without re-running any checks.

## Evidence conventions

- Static: `path/to/file.ts:LINE — what was seen`. Multiple locations on separate lines.
- Local/remote: `METHOD /path → STATUS (expected X)` plus a one-line body or header excerpt.
- Attest: what machinery was found, e.g. `Sentry initialized in app/layout.tsx:8; no alert routing config found`.
- Tool output: tool name and the relevant lines only, never the whole dump.
