#!/usr/bin/env python3
"""Coverage gate run before merge_findings.py: every check ID in each dispatched
domain's check file must appear in some findings/*.json (skipped checks included,
since the template records them). Prints missing IDs per domain; exit 1 if any."""
import argparse, json, sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from validate_checks import parse_checks


def missing_ids(findings_dir, checks_dir, domains):
    found = set()
    for f in sorted(Path(findings_dir).glob("*.json")):
        try:
            found |= {x["id"] for x in json.loads(f.read_text()) if isinstance(x, dict) and "id" in x}
        except (ValueError, OSError):
            pass
    out = {}
    for d in domains:
        p = Path(checks_dir) / f"{d}.md"
        expected = [c["id"] for c in parse_checks(p.read_text())] if p.exists() else []
        out[d] = [i for i in expected if i not in found]
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dir", default=".pre-launch")
    ap.add_argument("--checks", default=str(Path(__file__).resolve().parents[1] / "references/checks"))
    ap.add_argument("--domains", required=True)
    a = ap.parse_args()
    gaps = missing_ids(Path(a.dir) / "findings", a.checks, [d.strip() for d in a.domains.split(",") if d.strip()])
    bad = False
    for d, ids in gaps.items():
        if ids:
            bad = True
            print(f"{d}: missing {', '.join(ids)}")
        else:
            print(f"{d}: complete")
    sys.exit(1 if bad else 0)


if __name__ == "__main__":
    main()
