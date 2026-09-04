import sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "scripts"))
from merge_findings import merge, read_ticks, render

def f(id, status, domain="security", sev="critical", **kw):
    d = {"id": id, "title": f"T {id}", "domain": domain, "severity": sev, "status": status, "fix": "guided",
         "evidence": "ev", "recommendation": "rec", "verified_by": "static",
         "first_seen": None, "last_checked": None, "resolved": None, "commit": None, "notes": None}
    d.update(kw); return d

RUN = {"at": "2026-09-04T10:00:00Z", "domains": ["security"], "tiers": ["static"]}

def test_merge_preserves_first_seen_and_sets_resolved():
    prev = {"version": 1, "project": "p", "runs": [], "findings": [
        f("SEC-001", "fail", first_seen="2026-09-01T00:00:00Z", last_checked="2026-09-01T00:00:00Z"),
        f("DAT-001", "fail", domain="data", first_seen="2026-09-01T00:00:00Z")]}
    new = merge(prev, [f("SEC-001", "pass")], set(), RUN, "2026-09-04T10:00:00Z")
    by = {x["id"]: x for x in new["findings"]}
    assert by["SEC-001"]["first_seen"] == "2026-09-01T00:00:00Z"
    assert by["SEC-001"]["resolved"] == "2026-09-04T10:00:00Z"
    assert by["SEC-001"]["last_checked"] == "2026-09-04T10:00:00Z"
    assert by["DAT-001"]["status"] == "fail" and by["DAT-001"]["last_checked"] is None  # carried forward
    assert new["runs"][-1] == RUN

def test_merge_regression_clears_resolved_and_notes():
    prev = {"version": 1, "project": "p", "runs": [], "findings": [
        f("SEC-001", "pass", first_seen="2026-09-01T00:00:00Z", resolved="2026-09-02T00:00:00Z")]}
    new = merge(prev, [f("SEC-001", "fail")], set(), RUN, "2026-09-04T10:00:00Z")
    x = new["findings"][0]
    assert x["resolved"] is None and "regressed" in x["notes"]

def test_ticks_flip_attest_to_pass():
    prev = None
    new = merge(prev, [f("SEC-024", "attest")], {"SEC-024"}, RUN, "2026-09-04T10:00:00Z")
    x = new["findings"][0]
    assert x["status"] == "pass" and x["verified_by"] == "attested"

def test_read_ticks():
    md = "- [x] SEC-024 MFA — evidence: none\n- [ ] DAT-018 Backups — evidence: none\n"
    assert read_ticks(md) == {"SEC-024"}

def test_render_has_summary_and_delta():
    doc = merge(None, [f("SEC-001", "fail"), f("SEC-024", "attest", sev="medium"), f("SEO-001", "pass", domain="seo", sev="medium")],
                set(), RUN, "2026-09-04T10:00:00Z")
    doc["project"] = "acme"
    md = render(doc)
    assert md.startswith("# Pre-Launch Report — acme")
    assert "Blockers (critical, open): 1" in md
    assert "**SEC-001**" in md and "- [ ] SEC-024" in md
    assert md.index("## Security") < md.index("## SEO")
    assert "Since last run:" in md

def test_list_evidence_is_coerced():
    doc = merge(None, [f("SEC-001", "fail", evidence=["a.ts:1 — no header", "b.ts:2 — same"],
                         recommendation=["do x"], notes=None)],
                set(), RUN, "2026-09-04T10:00:00Z")
    x = doc["findings"][0]
    assert x["evidence"] == "a.ts:1 — no header\nb.ts:2 — same"
    assert x["recommendation"] == "do x"
    md = render(doc)                                  # used to crash on .splitlines()
    assert "- **SEC-001** T SEC-001 — critical — guided — a.ts:1 — no header" in md

def test_ticks_apply_to_carried_forward_findings():
    prev = {"version": 1, "project": "p", "runs": [], "findings": [
        f("SEC-024", "attest")]}
    new = merge(prev, [], {"SEC-024"}, RUN, "2026-09-04T10:00:00Z")
    x = new["findings"][0]
    assert x["status"] == "pass" and x["verified_by"] == "attested" and x["last_checked"] == "2026-09-04T10:00:00Z"

def _run(tmp, *args):
    import subprocess, os
    script = pathlib.Path(__file__).resolve().parents[1] / "scripts" / "merge_findings.py"
    return subprocess.run([sys.executable, str(script), "--dir", str(tmp), *args],
                          capture_output=True, text=True)

def test_bad_domain_file_is_skipped(tmp_path):
    import json
    (tmp_path / "findings").mkdir()
    (tmp_path / "findings" / "aaa-good.json").write_text(json.dumps([f("SEC-001", "fail")]))
    (tmp_path / "findings" / "bad.json").write_text('[{"id": "SEC-002",')  # truncated
    r = _run(tmp_path, "--domains", "security", "--tiers", "static")
    assert r.returncode == 0, r.stderr
    assert "skipped" in r.stderr and "bad.json" in r.stderr
    doc = json.loads((tmp_path / "findings.json").read_text())
    assert [x["id"] for x in doc["findings"]] == ["SEC-001"]

def test_domains_none_records_no_run(tmp_path):
    import json
    prev = {"version": 1, "project": "p", "runs": [RUN], "findings": [f("SEC-024", "attest")]}
    (tmp_path / "findings.json").write_text(json.dumps(prev))
    (tmp_path / "report.md").write_text("- [x] SEC-024 MFA — evidence: none\n")
    r = _run(tmp_path, "--domains", "none", "--tiers", "none")
    assert r.returncode == 0, r.stderr
    doc = json.loads((tmp_path / "findings.json").read_text())
    assert doc["runs"] == [RUN]                                  # no fake run appended
    assert doc["findings"][0]["status"] == "pass"                # ticks still applied
    assert "# Pre-Launch Report" in (tmp_path / "report.md").read_text()  # still re-rendered
    assert len(merge(prev, [], set(), RUN, "2026-09-04T10:00:00Z")["runs"]) == 2  # record_run default
