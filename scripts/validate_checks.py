#!/usr/bin/env python3
"""Dev-time linter: check blocks in references/checks/*.md and stack files in
references/stacks/*.md must match the spec inventory and required structure."""
import re, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SPEC = ROOT / "docs/superpowers/specs/2026-09-03-pre-launch-skill-design.md"
SEV = {"C": "critical", "H": "high", "M": "medium", "L": "low"}
TIER = {"S": "static", "L": "local", "R": "remote", "A": "attest"}
FIX = {"E": "easy", "G": "guided", "—": "none", "-": "none"}
FIELD_ORDER = ["severity", "tier", "fix", "when", "why", "verify", "evidence", "fix_hint"]
STACK_HEADINGS = [
    "detection signals", "dev server", "build", "env vars", "routes and handlers",
    "auth", "webhook handlers", "webhook verification snippet", "data access",
    "file uploads", "background jobs", "error handling and logging",
    "security headers", "known traps", "runtime probe hints",
]
HEAD_RE = re.compile(r"^### ([A-Z0-9]+-\d{3}) (.+)$", re.M)
ROW_RE = re.compile(r"^\| ([A-Z0-9]+-\d{3}) \| (.+?) \| ([CHML]) \| ([SLRA]) \| ([EG—-]) \|(?: (.*?) \|)?", re.M)
FLOW_ROW_RE = re.compile(r"^\| (FLOW-\d{3}) \| (.+?) \| ([CHML]) \|\s*(.*?)\s*\|", re.M)


def parse_checks(text):
    out = []
    heads = list(HEAD_RE.finditer(text))
    for i, h in enumerate(heads):
        body = text[h.end(): heads[i + 1].start() if i + 1 < len(heads) else len(text)]
        c = {"id": h.group(1), "title": h.group(2).strip()}
        for f in FIELD_ORDER:
            m = re.search(rf"^{f}:(.*?)(?=^\w+:|\Z)", body, re.M | re.S)
            c[f] = m.group(1).strip() if m else None
        out.append(c)
    return out


def spec_ids(spec_text):
    ids = {}
    for m in ROW_RE.finditer(spec_text):
        when = (m.group(6) or "").strip() or None
        ids[m.group(1)] = {"title": m.group(2).strip(), "severity": SEV[m.group(3)],
                           "tier": TIER[m.group(4)], "fix": FIX[m.group(5)], "when": when}
    for m in FLOW_ROW_RE.finditer(spec_text):
        if m.group(1) not in ids:
            ids[m.group(1)] = {"title": m.group(2).strip(), "severity": SEV[m.group(3)],
                               "tier": "local", "fix": "guided", "when": m.group(4).strip() or None}
    return ids


def validate(checks_dir, stacks_dir, spec_path):
    errs = []
    spec = spec_ids(spec_path.read_text()) if spec_path.exists() else {}
    seen = {}
    for f in sorted(Path(checks_dir).glob("*.md")):
        for c in parse_checks(f.read_text()):
            cid = c["id"]
            if cid in seen:
                errs.append(f"{f.name}: duplicate {cid} (also in {seen[cid]})")
            seen[cid] = f.name
            for req in ("severity", "tier", "fix", "why", "verify", "evidence"):
                if not c[req]:
                    errs.append(f"{f.name}: {cid} missing {req}")
            if c["fix"] != "none" and not c["fix_hint"]:
                errs.append(f"{f.name}: {cid} missing fix_hint")
            if cid in spec:
                for k in ("severity", "tier", "fix"):
                    if c[k] != spec[cid][k]:
                        errs.append(f"{f.name}: {cid} {k} is {c[k]!r}, spec says {spec[cid][k]!r}")
                if (c["when"] or None) != spec[cid]["when"]:
                    errs.append(f"{f.name}: {cid} when is {c['when']!r}, spec says {spec[cid]['when']!r}")
            else:
                errs.append(f"{f.name}: {cid} not in spec")
    for cid in spec:
        if cid not in seen:
            errs.append(f"spec {cid} missing from checks")
    for f in sorted(Path(stacks_dir).glob("*.md")):
        heads = [h.strip().lower() for h in re.findall(r"^## (.+)$", f.read_text(), re.M)]
        for h in STACK_HEADINGS:
            if h not in heads:
                errs.append(f"{f.name}: missing heading '{h}'")
    return errs


if __name__ == "__main__":
    e = validate(ROOT / "references/checks", ROOT / "references/stacks", SPEC)
    print("\n".join(e) if e else "OK")
    sys.exit(1 if e else 0)
