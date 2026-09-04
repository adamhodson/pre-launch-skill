#!/usr/bin/env python3
"""Merge per-domain findings into .pre-launch/findings.json and render report.md."""
import argparse, json, re, sys
from datetime import datetime, timezone
from pathlib import Path

DOMAIN_ORDER = ["security", "data", "payments", "flows", "reliability", "performance", "compliance",
                "access", "ai", "mobile", "accessibility", "seo", "hygiene"]
DOMAIN_TITLE = {"seo": "SEO", "ai": "AI", "accessibility": "Accessibility"}
SEV_ORDER = {"critical": 0, "high": 1, "medium": 2, "low": 3}
TICK_RE = re.compile(r"^- \[x\] ([A-Z0-9]+-\d{3})\b", re.M | re.I)


def read_ticks(report_md):
    return set(TICK_RE.findall(report_md or ""))


def text(v):
    """One string, whatever the auditor emitted (lists get joined with newlines)."""
    if isinstance(v, (list, tuple)):
        return "\n".join(str(x) for x in v)
    return v if isinstance(v, str) else ("" if v is None else str(v))


def coerce(f):
    """Auditors sometimes emit evidence as a list; report rendering wants one string."""
    f = dict(f)
    for k in ("evidence", "recommendation", "notes"):
        v = f.get(k)
        if v is None and k == "notes":
            continue
        f[k] = text(v)
    for k in ("id", "title", "domain", "severity", "status", "fix", "verified_by"):
        v = f.get(k)
        if v is not None and not isinstance(v, str):
            f[k] = str(v)
    return f


def merge(previous, domain_findings, ticked_ids, run, now, record_run=True):
    prev = {x["id"]: x for x in (previous or {}).get("findings", [])}
    out = dict(prev)
    delta = {"resolved": 0, "new": 0, "regressed": 0}
    for f in domain_findings:
        f = coerce(f)
        if f["id"] in ticked_ids and f["status"] == "attest":
            f["status"], f["verified_by"] = "pass", "attested"
        old = prev.get(f["id"])
        f["last_checked"] = now
        f["first_seen"] = old["first_seen"] if old and old.get("first_seen") else now
        f["commit"] = old.get("commit") if old else None
        f["resolved"] = old.get("resolved") if old else None
        if old is None:
            delta["new"] += 1 if f["status"] == "fail" else 0
        elif old["status"] == "fail" and f["status"] == "pass":
            f["resolved"] = now; delta["resolved"] += 1
        elif old["status"] == "pass" and f["status"] == "fail":
            f["resolved"] = None; f["notes"] = ((f.get("notes") or "") + " regressed").strip(); delta["regressed"] += 1
        out[f["id"]] = f
    # Ticked attestation boxes flip carried-forward (not re-checked this run) findings too.
    seen_ids = {f["id"] for f in domain_findings}
    for fid, x in out.items():
        if fid in seen_ids:
            continue
        if x.get("status") == "attest" and fid in ticked_ids:
            x = dict(x)
            x["status"], x["verified_by"], x["last_checked"] = "pass", "attested", now
            out[fid] = x
    doc = {"version": 1, "project": (previous or {}).get("project", Path.cwd().name),
           "runs": list((previous or {}).get("runs", [])) + ([run] if record_run else []),
           "findings": sorted(out.values(), key=lambda x: (DOMAIN_ORDER.index(x["domain"]) if x["domain"] in DOMAIN_ORDER else 99,
                                                           SEV_ORDER.get(x["severity"], 9), x["id"]))}
    doc["delta"] = delta
    return doc


def render(doc):
    fs = doc["findings"]; run = doc["runs"][-1] if doc["runs"] else {}
    d = doc.get("delta", {"resolved": 0, "new": 0, "regressed": 0})
    open_ = [x for x in fs if x["status"] == "fail"]
    blockers = [x for x in open_ if x["severity"] == "critical"]
    L = [f"# Pre-Launch Report — {doc['project']}",
         f"Last run: {run.get('at', '?')} · Domains: {', '.join(run.get('domains', []))} · Tiers: {', '.join(run.get('tiers', []))}",
         f"Since last run: {d['resolved']} resolved · {d['new']} new · {d['regressed']} regressed · {len(open_)} open", "",
         "## Launch readiness", f"Blockers (critical, open): {len(blockers)}", "",
         "| ID | Title | Domain | Status |", "|---|---|---|---|"]
    L += [f"| {x['id']} | {x['title']} | {x['domain']} | {x['status']} |" for x in blockers]
    L += ["", "| Severity | fail | attest | pass | skipped | error |", "|---|---|---|---|---|---|"]
    for sev in SEV_ORDER:
        row = [sum(1 for x in fs if x["severity"] == sev and x["status"] == s) for s in ("fail", "attest", "pass", "skipped", "error")]
        L.append(f"| {sev} | " + " | ".join(map(str, row)) + " |")
    for dom in DOMAIN_ORDER:
        xs = [x for x in fs if x["domain"] == dom]
        if not xs: continue
        L += ["", f"## {DOMAIN_TITLE.get(dom, dom.capitalize())}"]
        op = [x for x in xs if x["status"] == "fail"]
        if op:
            L += ["### Open"] + [f"- **{x['id']}** {x['title']} — {x['severity']} — {x['fix']} — {(text(x.get('evidence')).splitlines() or [''])[0]}" for x in op]
        at = [x for x in xs if x["status"] == "attest"]
        if at:
            L += ["### Attestation"] + [f"- [ ] {x['id']} {x['title']} — evidence: {text(x.get('evidence')) or 'none found'}" for x in at]
        ps = [x["id"] for x in xs if x["status"] == "pass"]
        if ps: L += ["### Passed", ", ".join(ps)]
        se = [x for x in xs if x["status"] in ("skipped", "error")]
        if se: L += ["### Skipped / Error"] + [f"- {x['id']} {x['title']} — {x['status']}: {text(x.get('notes'))}" for x in se]
    return "\n".join(L) + "\n"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dir", default=".pre-launch"); ap.add_argument("--domains", required=True); ap.add_argument("--tiers", required=True)
    a = ap.parse_args(); d = Path(a.dir)
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    prev = json.loads((d / "findings.json").read_text()) if (d / "findings.json").exists() else None
    ticks = read_ticks((d / "report.md").read_text()) if (d / "report.md").exists() else set()
    domain_findings = []
    for f in sorted((d / "findings").glob("*.json")):
        try:
            domain_findings += json.loads(f.read_text())
        except (json.JSONDecodeError, OSError) as e:
            print(f"skipped {f}: {e}", file=sys.stderr)
    run = {"at": now, "domains": a.domains.split(","), "tiers": a.tiers.split(",")}
    doc = merge(prev, domain_findings, ticks, run, now, record_run=a.domains != "none")
    d.mkdir(parents=True, exist_ok=True)
    (d / "findings.json").write_text(json.dumps(doc, indent=2))
    (d / "report.md").write_text(render(doc))
    print(render(doc).splitlines()[2])


if __name__ == "__main__":
    main()
