# Pre-Launch Skill Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the `/pre-launch` Claude Code skill: a 13-domain, 317-check audit of a project before production, with a report-driven fix phase.

**Architecture:** SKILL.md orchestrates detection, config, tier setup, and dispatch of one subagent per domain; subagents read a check reference plus stack references and write per-domain findings JSON; a small stdlib Python script merges findings and renders the report deterministically. Checks are markdown blocks with fixed fields; stack references answer fixed questions by heading. A validator script keeps the 317 check blocks and stack headings consistent with the spec.

**Tech Stack:** Markdown skill files; Python 3 stdlib scripts (no third-party deps); pytest for script tests; external tools invoked at audit time (gitleaks, npm audit, Lighthouse, axe, autocannon/k6) are not dependencies of the skill itself.

**Spec:** `docs/superpowers/specs/2026-09-03-pre-launch-skill-design.md`

## Global Constraints

- The project root `/Users/adamhodson/Documents/AI Dev/skills/pre-launch` IS the skill directory: `SKILL.md` lives at the root. The skill-creator workspace is the sibling `../pre-launch-workspace/`.
- Scripts are Python 3.9+ stdlib only. No pip installs for the skill to function.
- Check IDs are exactly those in spec section 8. Format `PREFIX-NNN`, three digits. Never reuse or renumber.
- Every check block has fields in this order: `severity`, `tier`, `fix`, `when` (optional), `why`, `verify`, `evidence`, `fix_hint` (omit `fix_hint` only when `fix: none`).
- Allowed values: severity `critical|high|medium|low`; tier `static|local|remote|attest`; fix `easy|guided|none`.
- Every stack file has all 15 required headings from spec 3.3, in order, even if a section says "not applicable".
- The audit phase never modifies project files and writes only under `.pre-launch/`.
- Deviation from spec 3.6, agreed for implementation: two extra bundled scripts. `scripts/merge_findings.py` merges domain findings and renders `report.md` deterministically (rendering 317 rows by hand from the LLM would drift). `scripts/validate_checks.py` is a dev-time linter and is not used at audit time.
- Commit after every task. Repo is initialized in Task 1.

## File Structure

```
pre-launch/                            (project root = skill root)
├── SKILL.md                           orchestrator: args, config, tiers, tools, dispatch, merge; fix phase
├── agents/domain-auditor.md           subagent prompt template
├── references/
│   ├── config-format.md               config.yml schema + detection heuristics
│   ├── report-format.md               findings.json schema, status semantics, merge rules, report layout
│   ├── checks/{security,data,performance,reliability,seo,accessibility,compliance,mobile,flows,payments,ai,hygiene,access}.md
│   └── stacks/{nextjs,nuxt,sveltekit,remix,astro,rails,django,laravel,express,fastapi,supabase,firebase,prisma,drizzle,stripe,revenuecat,lemonsqueezy,expo,react-native,flutter,vercel,netlify,cloudflare,fly}.md
├── scripts/
│   ├── probe_url.py                   URL prober → JSON
│   ├── merge_findings.py              findings/*.json + previous findings.json + report ticks → findings.json + report.md
│   └── validate_checks.py             dev lint: check blocks + stack headings vs spec
├── tests/
│   ├── test_probe_url.py
│   ├── test_merge_findings.py
│   └── test_validate_checks.py
└── evals/evals.json
```

---

### Task 1: Repo init and check-block validator

**Files:**
- Create: `.gitignore`, `scripts/validate_checks.py`, `tests/test_validate_checks.py`

**Interfaces:**
- Produces: `parse_checks(text: str) -> list[dict]` returning dicts with keys `id, title, severity, tier, fix, when, why, verify, evidence, fix_hint` (missing optional keys are `None`); `spec_ids(spec_text: str) -> dict[str, dict]` mapping ID → `{title, severity, tier, fix, when}` parsed from spec tables; `validate(checks_dir: Path, stacks_dir: Path, spec_path: Path) -> list[str]` returning error strings (empty list = valid). CLI: `python scripts/validate_checks.py` exits 1 and prints errors if any.
- Consumed by every check-file and stack-file task as the test.

- [ ] **Step 1: Init repo**

```bash
cd "/Users/adamhodson/Documents/AI Dev/skills/pre-launch"
git init
printf '.idea/\n__pycache__/\n.pytest_cache/\n.pre-launch/\n' > .gitignore
git add .gitignore Docs docs
git commit -m "chore: init repo with brainstorm docs, spec, and plan"
```

- [ ] **Step 2: Write the failing tests**

`tests/test_validate_checks.py`:

```python
import sys, pathlib, textwrap
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "scripts"))
from validate_checks import parse_checks, spec_ids, validate

BLOCK = textwrap.dedent("""
    ### SEC-051 Webhook signature verification
    severity: critical
    tier: local
    fix: guided
    when: features.payments
    why: A payment webhook without signature checks lets anyone mark orders paid.
    verify:
      static: Find every webhook handler (stack ref: "webhook handlers").
      local: POST a forged payload; expect 4xx.
    evidence: file:line per handler and probe status.
    fix_hint: Use constructEvent with the raw body.
""")

SPEC = textwrap.dedent("""
    ### 8.1 Security (SEC)
    | ID | Check | Sev | Tier | Fix | when |
    |---|---|---|---|---|---|
    | SEC-051 | Webhook signature verification on every webhook handler | C | L | G | |
    | SEC-024 | MFA available for admin accounts | M | A | — | |
""")

def test_parse_checks_reads_fields():
    c = parse_checks(BLOCK)[0]
    assert c["id"] == "SEC-051"
    assert c["title"] == "Webhook signature verification"
    assert c["severity"] == "critical" and c["tier"] == "local" and c["fix"] == "guided"
    assert c["when"] == "features.payments"
    assert "static:" in c["verify"] and "local:" in c["verify"]

def test_spec_ids_maps_abbreviations():
    ids = spec_ids(SPEC)
    assert ids["SEC-051"] == {"title": "Webhook signature verification on every webhook handler",
                              "severity": "critical", "tier": "local", "fix": "guided", "when": None}
    assert ids["SEC-024"]["fix"] == "none" and ids["SEC-024"]["tier"] == "attest"

def test_validate_reports_missing_and_mismatched(tmp_path):
    checks = tmp_path / "checks"; checks.mkdir()
    stacks = tmp_path / "stacks"; stacks.mkdir()
    (checks / "security.md").write_text(BLOCK.replace("tier: local", "tier: static"))
    spec = tmp_path / "spec.md"; spec.write_text(SPEC)
    errs = validate(checks, stacks, spec)
    assert any("SEC-051" in e and "tier" in e for e in errs)
    assert any("SEC-024" in e and "missing" in e for e in errs)

def test_validate_stack_headings(tmp_path):
    checks = tmp_path / "checks"; checks.mkdir()
    stacks = tmp_path / "stacks"; stacks.mkdir()
    (stacks / "nextjs.md").write_text("# nextjs\n## detection signals\nfoo\n")
    spec = tmp_path / "spec.md"; spec.write_text("")
    errs = validate(checks, stacks, spec)
    assert any("nextjs.md" in e and "dev server" in e for e in errs)
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `cd "/Users/adamhodson/Documents/AI Dev/skills/pre-launch" && python3 -m pytest tests/test_validate_checks.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'validate_checks'`

- [ ] **Step 4: Implement `scripts/validate_checks.py`**

```python
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
FLOW_ROW_RE = re.compile(r"^\| (FLOW-\d{3}) \| (.+?) \| ([CHML]) \| (.*?) \|", re.M)


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
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `python3 -m pytest tests/test_validate_checks.py -v`
Expected: 4 passed

- [ ] **Step 6: Commit**

```bash
git add scripts/validate_checks.py tests/test_validate_checks.py
git commit -m "feat: add check-block validator"
```

---

### Task 2: URL prober script

**Files:**
- Create: `scripts/probe_url.py`, `tests/test_probe_url.py`

**Interfaces:**
- Produces: `probe(base_url: str, timeout: float = 10.0) -> dict` and CLI `python scripts/probe_url.py <base_url>` printing JSON. Output shape:

```json
{
  "base": "http://localhost:3000",
  "pages": {
    "/": {"status": 200, "headers": {"content-type": "..."}, "redirects": ["http://...", "..."],
          "title": "…", "description": "…", "canonical": "…", "lang": "en",
          "og": {"og:title": "…"}, "twitter": {"twitter:card": "…"},
          "jsonld": [{"@type": "Organization"}], "h1_count": 1,
          "links": ["https://…"], "images_without_alt": 2},
    "/robots.txt": {"status": 200, "body": "User-agent: *…"},
    "/sitemap.xml": {"status": 200, "urls": ["https://…"]},
    "/llms.txt": {"status": 404, "body": ""},
    "/__prelaunch_missing__": {"status": 404, "body_snippet": "…"}
  },
  "sensitive_paths": {"/.git/HEAD": 404, "/.env": 404, "/backup.sql": 404, "/config.json": 404}
}
```
- Consumed by SEO, security (SEC-007, 032-036, 056, 065, 066), hygiene (HYG-002, 005) checks and by `domain-auditor.md`.

- [ ] **Step 1: Write the failing test**

`tests/test_probe_url.py`:

```python
import sys, pathlib, threading, json
from http.server import BaseHTTPRequestHandler, HTTPServer
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "scripts"))
from probe_url import probe

HTML = b"""<!doctype html><html lang="en"><head><title>Acme</title>
<meta name="description" content="Widgets"><link rel="canonical" href="https://acme.test/">
<meta property="og:title" content="Acme"><meta name="twitter:card" content="summary">
<script type="application/ld+json">{"@type":"Organization","name":"Acme"}</script>
</head><body><h1>Hi</h1><a href="/about">About</a><img src="a.png"><img src="b.png" alt="B"></body></html>"""

class H(BaseHTTPRequestHandler):
    def do_GET(self):
        routes = {"/": (200, HTML, "text/html"),
                  "/robots.txt": (200, b"User-agent: *\nSitemap: /sitemap.xml", "text/plain"),
                  "/sitemap.xml": (200, b'<urlset><url><loc>https://acme.test/</loc></url></urlset>', "application/xml")}
        status, body, ctype = routes.get(self.path, (404, b"nope", "text/plain"))
        self.send_response(status); self.send_header("Content-Type", ctype); self.end_headers(); self.wfile.write(body)
    def log_message(self, *a): pass

def test_probe_extracts_seo_fields():
    srv = HTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{srv.server_port}"
    out = probe(base)
    root = out["pages"]["/"]
    assert root["status"] == 200 and root["title"] == "Acme" and root["lang"] == "en"
    assert root["description"] == "Widgets" and root["canonical"] == "https://acme.test/"
    assert root["og"]["og:title"] == "Acme" and root["twitter"]["twitter:card"] == "summary"
    assert root["jsonld"][0]["@type"] == "Organization"
    assert root["h1_count"] == 1 and root["images_without_alt"] == 1 and "/about" in root["links"]
    assert out["pages"]["/sitemap.xml"]["urls"] == ["https://acme.test/"]
    assert out["pages"]["/llms.txt"]["status"] == 404
    assert out["pages"]["/__prelaunch_missing__"]["status"] == 404
    assert out["sensitive_paths"]["/.env"] == 404
    json.dumps(out)  # serializable
    srv.shutdown()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/test_probe_url.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'probe_url'`

- [ ] **Step 3: Implement `scripts/probe_url.py`**

```python
#!/usr/bin/env python3
"""Fetch a site's key URLs and emit SEO/security-relevant facts as JSON. Stdlib only."""
import json, re, sys, urllib.request, urllib.error
from html.parser import HTMLParser

SENSITIVE = ["/.git/HEAD", "/.env", "/backup.sql", "/config.json", "/.DS_Store", "/phpinfo.php", "/server-status"]
MISSING = "/__prelaunch_missing__"


class Page(HTMLParser):
    def __init__(self):
        super().__init__()
        self.title = None; self.description = None; self.canonical = None; self.lang = None
        self.og = {}; self.twitter = {}; self.jsonld = []; self.h1_count = 0; self.links = []
        self.images_without_alt = 0; self._in_title = False; self._in_ld = False; self._buf = ""

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag == "html" and a.get("lang"): self.lang = a["lang"]
        elif tag == "title": self._in_title = True; self._buf = ""
        elif tag == "meta":
            name, prop, content = a.get("name", ""), a.get("property", ""), a.get("content", "")
            if name == "description": self.description = content
            if prop.startswith("og:"): self.og[prop] = content
            if name.startswith("twitter:"): self.twitter[name] = content
        elif tag == "link" and a.get("rel") == "canonical": self.canonical = a.get("href")
        elif tag == "script" and a.get("type") == "application/ld+json": self._in_ld = True; self._buf = ""
        elif tag == "h1": self.h1_count += 1
        elif tag == "a" and a.get("href"): self.links.append(a["href"])
        elif tag == "img" and not a.get("alt"): self.images_without_alt += 1

    def handle_data(self, data):
        if self._in_title or self._in_ld: self._buf += data

    def handle_endtag(self, tag):
        if tag == "title" and self._in_title: self.title = self._buf.strip(); self._in_title = False
        if tag == "script" and self._in_ld:
            self._in_ld = False
            try: self.jsonld.append(json.loads(self._buf))
            except json.JSONDecodeError: self.jsonld.append({"_invalid": self._buf[:200]})


def fetch(url, timeout):
    redirects = []
    class NoRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, req, fp, code, msg, headers, newurl):
            redirects.append(newurl); return super().redirect_request(req, fp, code, msg, headers, newurl)
    opener = urllib.request.build_opener(NoRedirect)
    req = urllib.request.Request(url, headers={"User-Agent": "pre-launch-probe/1"})
    try:
        with opener.open(req, timeout=timeout) as r:
            return r.status, dict((k.lower(), v) for k, v in r.headers.items()), r.read(), redirects
    except urllib.error.HTTPError as e:
        return e.code, dict((k.lower(), v) for k, v in e.headers.items()), e.read(), redirects
    except Exception as e:
        return None, {}, str(e).encode(), redirects


def probe(base_url, timeout=10.0):
    base = base_url.rstrip("/")
    out = {"base": base, "pages": {}, "sensitive_paths": {}}
    for path in ["/", "/robots.txt", "/sitemap.xml", "/llms.txt", MISSING]:
        status, headers, body, redirects = fetch(base + path, timeout)
        text = body.decode("utf-8", "replace")
        entry = {"status": status, "headers": headers, "redirects": redirects}
        if path == "/" and status == 200:
            p = Page(); p.feed(text)
            entry.update(title=p.title, description=p.description, canonical=p.canonical, lang=p.lang,
                         og=p.og, twitter=p.twitter, jsonld=p.jsonld, h1_count=p.h1_count,
                         links=p.links, images_without_alt=p.images_without_alt)
        elif path == "/sitemap.xml":
            entry["urls"] = re.findall(r"<loc>\s*(.*?)\s*</loc>", text)
        elif path == MISSING:
            entry["body_snippet"] = text[:500]
        else:
            entry["body"] = text[:5000] if status == 200 else ""
        out["pages"][path] = entry
    for path in SENSITIVE:
        out["sensitive_paths"][path] = fetch(base + path, timeout)[0]
    return out


if __name__ == "__main__":
    if len(sys.argv) < 2:
        sys.exit("usage: probe_url.py <base_url>")
    print(json.dumps(probe(sys.argv[1]), indent=2))
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m pytest tests/test_probe_url.py -v`
Expected: 1 passed

- [ ] **Step 5: Commit**

```bash
git add scripts/probe_url.py tests/test_probe_url.py
git commit -m "feat: add stdlib URL prober"
```

---

### Task 3: Findings merger and report renderer

**Files:**
- Create: `scripts/merge_findings.py`, `tests/test_merge_findings.py`

**Interfaces:**
- Produces: `merge(previous: dict | None, domain_findings: list[dict], ticked_ids: set[str], run: dict, now: str) -> dict` returning the new findings.json document; `read_ticks(report_md: str) -> set[str]` returning IDs whose attestation checkbox is `[x]`; `render(findings: dict) -> str` returning report.md text; CLI `python scripts/merge_findings.py --dir .pre-launch --domains security,data --tiers static,local` reading `.pre-launch/findings/*.json`, previous `findings.json`, and `report.md`, writing both outputs and printing the delta line.
- Finding object fields (spec 5.1): `id, title, domain, severity, status, fix, evidence, recommendation, verified_by, first_seen, last_checked, resolved, commit, notes`.
- Domain order for the report: `security, data, payments, flows, reliability, performance, compliance, access, ai, mobile, accessibility, seo, hygiene`.

- [ ] **Step 1: Write the failing tests**

`tests/test_merge_findings.py`:

```python
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m pytest tests/test_merge_findings.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'merge_findings'`

- [ ] **Step 3: Implement `scripts/merge_findings.py`**

```python
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


def merge(previous, domain_findings, ticked_ids, run, now):
    prev = {x["id"]: x for x in (previous or {}).get("findings", [])}
    out = dict(prev)
    delta = {"resolved": 0, "new": 0, "regressed": 0}
    for f in domain_findings:
        f = dict(f)
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
    doc = {"version": 1, "project": (previous or {}).get("project", Path.cwd().name),
           "runs": list((previous or {}).get("runs", [])) + [run],
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
            L += ["### Open"] + [f"- **{x['id']}** {x['title']} — {x['severity']} — {x['fix']} — {(x['evidence'] or '').splitlines()[0] if x['evidence'] else ''}" for x in op]
        at = [x for x in xs if x["status"] == "attest"]
        if at:
            L += ["### Attestation"] + [f"- [ ] {x['id']} {x['title']} — evidence: {x['evidence'] or 'none found'}" for x in at]
        ps = [x["id"] for x in xs if x["status"] == "pass"]
        if ps: L += ["### Passed", ", ".join(ps)]
        se = [x for x in xs if x["status"] in ("skipped", "error")]
        if se: L += ["### Skipped / Error"] + [f"- {x['id']} {x['title']} — {x['status']}: {x['notes'] or ''}" for x in se]
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
        domain_findings += json.loads(f.read_text())
    run = {"at": now, "domains": a.domains.split(","), "tiers": a.tiers.split(",")}
    doc = merge(prev, domain_findings, ticks, run, now)
    (d / "findings.json").write_text(json.dumps(doc, indent=2))
    (d / "report.md").write_text(render(doc))
    print(render(doc).splitlines()[2])


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 -m pytest tests/test_merge_findings.py -v`
Expected: 5 passed

- [ ] **Step 5: Commit**

```bash
git add scripts/merge_findings.py tests/test_merge_findings.py
git commit -m "feat: add findings merger and report renderer"
```

---

### Task 4: Reference docs for config and report formats

**Files:**
- Create: `references/config-format.md`, `references/report-format.md`

**Interfaces:**
- Consumes: finding fields and merge rules from Task 3; config shape from spec section 4.
- Produces: the two documents SKILL.md tells the orchestrator and subagents to read. Detection heuristics table is the source for Task 25's detect step.

- [ ] **Step 1: Write `references/config-format.md`**

Copy the YAML block from spec section 4 verbatim under a `## Schema` heading, then add:

```markdown
## Detection heuristics

Run these in order; each match appends to `stacks`, `platforms`, or sets a feature. Show the result to the user once and accept corrections before writing the file.

| Signal | Sets |
|---|---|
| `next` in package.json deps | stacks: nextjs; platforms: web |
| `nuxt` in deps | stacks: nuxt; platforms: web |
| `@sveltejs/kit` in deps | stacks: sveltekit; platforms: web |
| `@remix-run/*` in deps | stacks: remix; platforms: web |
| `astro` in deps | stacks: astro; platforms: web |
| `express` in deps | stacks: express |
| `fastapi` in requirements/pyproject | stacks: fastapi |
| `django` in requirements/pyproject | stacks: django |
| `rails` in Gemfile | stacks: rails |
| `laravel/framework` in composer.json | stacks: laravel |
| `supabase/` dir or `@supabase/supabase-js` | stacks: supabase |
| `firebase.json` or `firebase`/`firebase-admin` dep | stacks: firebase |
| `prisma/schema.prisma` | stacks: prisma |
| `drizzle.config.*` | stacks: drizzle |
| `stripe` dep | stacks: stripe; features.payments: true |
| `react-native-purchases` or `purchases-*` dep | stacks: revenuecat; features.payments: true |
| `@lemonsqueezy/*` dep | stacks: lemonsqueezy; features.payments: true |
| `app.json` with `expo` key or `expo` dep | stacks: expo; platforms: ios, android |
| `ios/` and `android/` dirs without expo | stacks: react-native; platforms: ios, android |
| `pubspec.yaml` | stacks: flutter; platforms: ios, android |
| `vercel.json` or `.vercel/` | stacks: vercel |
| `netlify.toml` | stacks: netlify |
| `wrangler.toml` | stacks: cloudflare |
| `fly.toml` | stacks: fly |
| `openai`, `@anthropic-ai/sdk`, `anthropic`, `ai` (Vercel AI SDK), `langchain*` dep | features.ai: true |
| grep `subscription` in schema/migrations or Stripe price objects with `recurring` | features.subscriptions: true |
| grep `trial` in schema, Stripe config, or pricing pages | features.trials: true |
| storage bucket config, `multer`, `formidable`, `busboy`, `<input type="file">` | features.uploads: true |
| tables/models named `comment`, `post`, `review`, `message` with a user FK | features.user_content: true |
| `resend`, `nodemailer`, `@sendgrid/mail`, `postmark`, ActionMailer, Django email backend | features.email_sending: true |
| `twilio`, `vonage` dep | features.sms: true |
| tables/models named `organization`, `team`, `workspace`, `membership` | features.teams: true |
| supabase realtime channel usage, `socket.io`, `ws` dep, Pusher/Ably | features.realtime: true |
| `graphql`, `apollo-server`, `graphql-yoga` dep | features.graphql: true |
| `expo-local-authentication`, `react-native-biometrics`, face/voice SDKs | features.biometrics: true |
| i18n libraries (`next-intl`, `i18next`, `vue-i18n`) with more than one locale | features.multilingual: true |

Undetectable flags (`health_data`, `minors_possible`, `b2b`) default to false and are listed explicitly in the confirmation prompt.

## Local environment

- `local.url`: default from framework default port (nextjs/nuxt/remix/astro 3000, sveltekit 5173, django 8000, rails 3000, laravel 8000, fastapi 8000, express: read `PORT` default or ask). Ask if none applies.
- `local.start`: package.json `dev` script → `npm run dev` (or `pnpm`/`yarn`/`bun` per lockfile); `Procfile` web line; `docker-compose.yml` → `docker compose up`; `manage.py` → `python manage.py runserver`; `bin/rails` → `bin/rails s`; `artisan` → `php artisan serve`. Ask if ambiguous. `null` means the user starts it.
- `ready_path` defaults to `/`.

## Skips

`skip` entries need a `reason`. Skipped checks appear in the report under Skipped with that reason so a reviewer sees what was consciously waived.
```

- [ ] **Step 2: Write `references/report-format.md`**

Copy spec sections 5.1, 5.2, 5.3 verbatim, then add:

```markdown
## Per-domain findings files

Each domain subagent writes `.pre-launch/findings/<domain>.json`: a JSON array of finding objects with every field present (`null` where unknown). `first_seen`, `last_checked`, `resolved`, and `commit` are always `null` in domain files; the merger owns them. Write the file after each check completes (rewrite the whole array) so a crash keeps prior results.

## Merging

Run from the project root after all subagents finish:

    python3 <skill-dir>/scripts/merge_findings.py --dir .pre-launch --domains <comma list> --tiers <comma list>

It reads `.pre-launch/findings/*.json`, previous `findings.json`, and ticked boxes in `report.md`; writes both files; prints the delta line. Delete `.pre-launch/findings/` afterwards so a later scoped run does not re-merge stale domain files.

## Evidence conventions

- Static: `path/to/file.ts:LINE — what was seen`. Multiple locations on separate lines.
- Local/remote: `METHOD /path → STATUS (expected X)` plus a one-line body or header excerpt.
- Attest: what machinery was found, e.g. `Sentry initialized in app/layout.tsx:8; no alert routing config found`.
- Tool output: tool name and the relevant lines only, never the whole dump.
```

- [ ] **Step 3: Verify both files reference nothing undefined**

Run: `grep -c "" references/config-format.md references/report-format.md && grep -n "TBD\|TODO" references/*.md; echo "exit $?"`
Expected: line counts printed; grep finds nothing (exit 1).

- [ ] **Step 4: Commit**

```bash
git add references/config-format.md references/report-format.md
git commit -m "docs: add config and report format references"
```

---

### Task 5: Domain auditor subagent template

**Files:**
- Create: `agents/domain-auditor.md`

**Interfaces:**
- Consumes: check block format (Task 1), finding fields and domain-file conventions (Task 4), `probe_url.py` output (Task 2).
- Produces: the prompt SKILL.md (Task 25) fills with `{{domain}}`, `{{check_file}}`, `{{stack_files}}`, `{{config}}`, `{{tiers}}`, `{{test_account_path}}`, `{{previous_findings}}`, `{{budget_minutes}}`, `{{skill_dir}}`, `{{project_dir}}`.

- [ ] **Step 1: Write `agents/domain-auditor.md`**

```markdown
# Domain auditor: {{domain}}

You are auditing the project at `{{project_dir}}` for the **{{domain}}** domain of a pre-launch review. Your output is a findings file, not a fix. You never modify project files and never write outside `{{project_dir}}/.pre-launch/`.

## Inputs

- Check file: `{{check_file}}` — read it fully first. Every `###` block is one check.
- Stack references: {{stack_files}} — read the headings a check points at with `(stack ref: "...")`. They tell you where things live on this stack; they contain no checks.
- Config: `{{config}}` — feature flags, URLs, skip list.
- Live tiers: {{tiers}}. A check whose `tier` is not in this list cannot be verified at that tier.
- Test account: `{{test_account_path}}` (may not exist). Use only this account for any runtime probe involving auth. Never touch real user data.
- Previous findings for this domain: {{previous_findings}} — use as a hint of where to look, never as a verdict.
- Time budget: {{budget_minutes}} minutes for the whole domain. Track elapsed time; if you run out, write remaining checks as `error` with `notes: "budget exceeded"`.
- Helper: `python3 {{skill_dir}}/scripts/probe_url.py <url>` returns headers, meta, robots, sitemap, llms.txt, 404 behavior, and sensitive-path statuses as JSON. Call it once per base URL and reuse the output.

## Procedure

Work through every check in file order. For each:

1. **Applicability.** If the check has a `when:` clause and the config evaluates it false, or the ID is in `skip`, write `status: skipped` with the reason in `notes`. Never drop a check silently.
2. **Pick the tier.** Use the highest tier in the check's `verify` block that is also in the live tiers. If none is live and the check has a `static` verify, use static. If nothing can run, `status: error`, `notes: "tier <x> unavailable"`.
3. **Verify.** Do what the verify block says, on this stack, using the stack reference for locations. Search the actual code; do not infer from file names alone. For runtime probes cap each request at 30 seconds.
4. **Decide.** `pass` only when you saw the defense or behavior. `fail` when you saw its absence or a bad response. `attest` when the check's tier is `attest` or you could confirm machinery exists but not that a human did the process. `error` when you could not complete the check; say why.
5. **Record.** Append a finding object and rewrite `{{project_dir}}/.pre-launch/findings/{{domain}}.json` as a JSON array. Fields: `id, title, domain, severity, status, fix, evidence, recommendation, verified_by, first_seen: null, last_checked: null, resolved: null, commit: null, notes`. `verified_by` is the tier you actually used (`static`, `local`, `remote`, `attest`, or `static-fallback` when a preferred tool was unavailable). `recommendation` is one or two sentences derived from `fix_hint`, made specific to what you found.

## Evidence

Evidence is what a reviewer needs to confirm your verdict without redoing your work. Static: `file:line — what was seen`, one per line. Runtime: `METHOD /path → STATUS (expected X)` plus a short excerpt. Attest: what machinery was found and what was not. Tool output: tool name and the relevant lines only.

## Rules that matter

- A check with no evidence is not a pass. If you did not look, it is `error`, not `pass`.
- One finding per check ID, even when a check found many locations; put all locations in `evidence`.
- Runtime probes that could mutate data (uploads, sign-ups, deletions, payments) use only the test account and test-mode keys. If test-mode keys are not detectable, mark the probe `error` rather than risking a live side effect.
- Load tests belong only to the performance domain and only against `local.url`, never `remote.url`.
- Legal and policy checks compare page text against what the codebase actually does; quote the relevant sentence or note its absence.
- When done, print a one-line summary: `{{domain}}: N pass, N fail, N attest, N skipped, N error`.
```

- [ ] **Step 2: Sanity-check placeholders are consistent**

Run: `grep -o "{{[a-z_]*}}" agents/domain-auditor.md | sort -u`
Expected: exactly `{{budget_minutes}} {{check_file}} {{config}} {{domain}} {{previous_findings}} {{project_dir}} {{skill_dir}} {{stack_files}} {{test_account_path}} {{tiers}}`

- [ ] **Step 3: Commit**

```bash
git add agents/domain-auditor.md
git commit -m "feat: add domain auditor subagent template"
```

---

## Check file tasks (6–18)

Each of the next thirteen tasks writes one `references/checks/<domain>.md`. They share the same shape; each task below repeats the steps so it can be executed alone.

**Authoring rules for every check block** (the validator enforces the first four; a reviewer enforces the rest):

1. Heading `### <ID> <Title>` where ID, title, severity, tier, fix, and `when` come from the spec table for that domain. Title may be shortened but must keep the meaning.
2. Fields in this order: `severity`, `tier`, `fix`, `when` (only if the spec row has one), `why`, `verify`, `evidence`, `fix_hint` (omit only when `fix: none`).
3. `verify` has one sub-entry per tier the check can use, from lowest to highest (`static:`, `local:`, `remote:`, `attest:`). Include a `static:` entry whenever code inspection can say anything useful, so a codebase-only run still produces a verdict.
4. Each `verify` entry is concrete: name what to search for (a pattern, a file type, a config key), which stack heading to consult in quotes, what tool to run if any, what request to send, and what result means pass versus fail.
5. `why` is one or two sentences on the real-world consequence, written for a developer who might argue the check is unnecessary.
6. `fix_hint` names the mechanism, not the whole patch: which file type to edit, which library call or config key, and which stack heading has the snippet.
7. Blocks are ordered by ID.

### Task 6: Security checks

**Files:**
- Create: `references/checks/security.md`

**Interfaces:**
- Consumes: spec section 8.1 (SEC-001 to SEC-067) for ID/severity/tier/fix/when; stack headings from spec 3.3.
- Produces: 67 check blocks read by the security subagent.

- [ ] **Step 1: Write the file header and all 67 blocks**

Header:

```markdown
# Security checks (SEC)

Read `agents/domain-auditor.md` for procedure. Blocks below are checks; consult stack references for locations. Tools: gitleaks (SEC-001, 002), `npm audit`/`pip-audit`/`bundler-audit`/`composer audit` (SEC-057), `probe_url.py` (SEC-007, 032–036, 056, 065, 066).
```

Two fully worked blocks that set the bar; write the remaining 65 to the same standard:

```markdown
### SEC-001 No hardcoded secrets or API keys in source
severity: critical
tier: static
fix: easy
why: A key in source ships to every clone, CI log, and bundle. Once leaked it must be rotated, and most teams find out from a bill.
verify:
  static: Run `gitleaks detect --no-git --source . --report-format json` if installed; otherwise grep the tree (excluding node_modules, .git, lockfiles, and build output) for provider prefixes: `sk_live_`, `sk_test_`, `rk_live_`, `whsec_`, `AKIA[0-9A-Z]{16}`, `AIza[0-9A-Za-z_-]{35}`, `ghp_`, `xox[bp]-`, `-----BEGIN (RSA |EC )?PRIVATE KEY`, `eyJhbGciOi` outside test fixtures, and any assignment of `SECRET|TOKEN|PASSWORD|API_KEY` to a literal longer than 16 chars. Values read from `process.env`, `os.environ`, `ENV[...]`, `env(...)` are fine (stack ref: "env vars"). Test fixtures with obviously fake values pass; note them.
evidence: file:line and the redacted first 6 characters of each match; tool name used.
fix_hint: Move the literal to the environment loader named under stack ref "env vars", add the variable to `.env.example` with a placeholder, and tell the user the key must be rotated because it is already in history (see SEC-002).

### SEC-011 Object-level authorization on reads, mutations, and subresources (IDOR)
severity: critical
tier: local
fix: guided
why: Sequential or guessable IDs plus a missing ownership check is the most common way one user reads another user's invoices, messages, or files.
verify:
  static: List every route, server action, or RPC that takes an ID parameter (stack ref: "routes and handlers"). For each, confirm the query is scoped by the current user or org (a `where user_id = session.user.id`, an RLS policy covering the table per DAT-002, or an explicit ownership check) before returning or mutating. Subresources count: `/orders/:id/invoice` must check the order's owner, not just that the order exists.
  local: Using the test account (stack ref: "runtime probe hints" for the auth cookie), create a resource, note its ID, then request it with a second test account or no auth. Expect 401/403/404, never 200 with the first account's data. Try at least one read, one mutation, and one subresource.
evidence: per route: `file:line — scoped by <what>` or `file:line — NOT scoped`; probe lines `GET /api/orders/<id> as other user → 200 (expected 403)`.
fix_hint: Add the ownership predicate to the query in the data access layer (stack ref: "data access") rather than in each handler, or enable the RLS policy that enforces it; re-run the probe.
```

Coverage notes for the rest, so nothing is skipped or misread:
- SEC-003: search for the public env prefix named in the stack ref (`NEXT_PUBLIC_`, `VITE_`, `EXPO_PUBLIC_`, `NUXT_PUBLIC_`) assigned to anything named like a secret; also grep the built client bundle if `build` output exists.
- SEC-008: playgrounds include `/graphql` GET, `/_debug`, `/__nuxt`, Django `DEBUG=True`, Rails `config.consider_all_requests_local`, Laravel `APP_DEBUG=true`.
- SEC-015: name the endpoints that must be limited: login, sign-up, reset, OTP, contact forms, email/SMS send, AI, export, search.
- SEC-031: CSP passes if present and not `default-src *` with `unsafe-inline` everywhere; note report-only mode as fail.
- SEC-043: include `dangerouslySetInnerHTML`, `v-html`, `{@html}`, `innerHTML =`, `raw()`, `html_safe`, `|safe`, `{!! !!}` and confirm each is fed sanitized or trusted content.
- SEC-047 local probe: upload a file named `photo.jpg` whose bytes start with `<?php` and one named `shell.php.jpg`; expect rejection; confirm the server sniffs content, not just extension.
- SEC-051 local probe: POST to each webhook path with a valid-looking body and a bad signature header; expect 4xx.
- SEC-066 remote/local: read `sensitive_paths` from `probe_url.py` output; any 200 is a fail.

- [ ] **Step 2: Validate**

Run: `python3 scripts/validate_checks.py`
Expected: errors only for domains not yet written (`spec DAT-001 missing from checks`, etc.); no line mentioning `security.md`.

- [ ] **Step 3: Count blocks**

Run: `grep -c "^### SEC-" references/checks/security.md`
Expected: `67`

- [ ] **Step 4: Commit**

```bash
git add references/checks/security.md
git commit -m "feat(checks): add security domain (SEC-001..067)"
```

---

### Task 7: Data checks

**Files:**
- Create: `references/checks/data.md`

**Interfaces:**
- Consumes: spec 8.2 (DAT-001 to DAT-027).
- Produces: 27 blocks for the data subagent.

- [ ] **Step 1: Write the header and all 27 blocks**

Header: `# Data checks (DAT)` plus the tools line: `psql` or the Supabase CLI for DAT-002 policy probes; Firebase emulator or `firebase` CLI for DAT-003.

Worked block:

```markdown
### DAT-002 Policies tested as anon, owner, and another user
severity: critical
tier: local
fix: guided
why: RLS being enabled says nothing about whether the policies are right. A policy with `USING (true)` or a missing `WITH CHECK` passes DAT-001 and still leaks everything.
verify:
  static: For each table with RLS (stack ref: "data access"), read every policy. Fail if any policy on a user-data table uses `true` as its predicate, lacks `WITH CHECK` on insert/update, or references `auth.uid()` on a nullable column without a null guard. Note tables with no policy at all (RLS on with no policy blocks everyone, which breaks the app rather than leaking, but is still a fail).
  local: With the anon key and no session, select from each user-data table; expect zero rows. With the test account's JWT, insert a row, then with a second test JWT try to select, update, and delete it; expect zero rows or a permission error. Use the stack ref for how to obtain a JWT for the test account.
evidence: per table: policy names and predicates; probe results `select <table> as anon → N rows (expected 0)`.
fix_hint: Rewrite the policy predicate to compare the row's owner column to `auth.uid()` (or the equivalent claim) and add a matching WITH CHECK; snippet under stack ref "data access".
```

Coverage notes:
- DAT-009: read the schema and list every foreign key column; grep migrations for an index on each; also match `where`/`orderBy` columns in the data access layer against indexes.
- DAT-015 local: create a scratch database (SQLite or a fresh Postgres schema via the stack's migration tool) and run all migrations from zero; fail on any error.
- DAT-017: inspect deploy config and env files for preview/branch environments; fail if `DATABASE_URL` or the Supabase project ref for previews equals production's.
- DAT-020 local: this check is the runtime half of FLOW-009; if the flows domain already ran FLOW-009 in this run, read its finding and reuse the evidence instead of deleting a second account.

- [ ] **Step 2: Validate** — Run: `python3 scripts/validate_checks.py`; Expected: no line mentioning `data.md`.
- [ ] **Step 3: Count** — Run: `grep -c "^### DAT-" references/checks/data.md`; Expected: `27`
- [ ] **Step 4: Commit**

```bash
git add references/checks/data.md
git commit -m "feat(checks): add data domain (DAT-001..027)"
```

---

### Task 8: Performance checks

**Files:**
- Create: `references/checks/performance.md`

**Interfaces:**
- Consumes: spec 8.3 (PERF-001 to PERF-020).
- Produces: 20 blocks. PERF-001 produces a measurement finding (`fix: none`) whose evidence holds the numbers other checks cite.

- [ ] **Step 1: Write the header and all 20 blocks**

Header: `# Performance checks (PERF)` with the ordering rule: this domain runs after all others; load tests hit `local.url` only.

Worked block:

```markdown
### PERF-001 Load test key endpoints; record p50/p95/p99 and error rate
severity: high
tier: local
fix: none
why: The first real traffic spike is the wrong time to learn that the dashboard query takes four seconds under ten concurrent users.
verify:
  static: Identify the five most important endpoints: the landing page, the authenticated home/dashboard, the heaviest list endpoint, the checkout or primary action, and one write endpoint (stack ref: "routes and handlers"). Record them in evidence even if the local tier is unavailable.
  local: For each endpoint run `npx autocannon -c 20 -d 20 -H "cookie: <test session>" <url>` (or `k6 run` with an equivalent script if k6 is installed and autocannon is not). Record requests/sec, p50, p95, p99 latency, and non-2xx count. Status is `pass` when every endpoint's p95 is under 1000 ms and error rate under 1%; `fail` otherwise. Always record the numbers.
evidence: table of endpoint, rps, p50, p95, p99, errors; tool and flags used.
```

Coverage notes:
- PERF-002 reads PERF-001's numbers and names the slowest; static tier traces outbound calls in the request path (stack ref: "background jobs" for what should be async).
- PERF-011 local: `npx lighthouse <local.url> --only-categories=performance --output=json --quiet --chrome-flags="--headless"`; thresholds LCP 2.5 s, CLS 0.1, INP 200 ms.
- PERF-017: search for read-then-write on balances, credits, inventory, or seats without a transaction, row lock, or atomic update.
- PERF-020: read platform limits from the deploy stack ref ("known traps") and compare against handlers that stream, upload, or wait on AI calls.

- [ ] **Step 2: Validate** — Run: `python3 scripts/validate_checks.py`; Expected: no line mentioning `performance.md`.
- [ ] **Step 3: Count** — Run: `grep -c "^### PERF-" references/checks/performance.md`; Expected: `20`
- [ ] **Step 4: Commit**

```bash
git add references/checks/performance.md
git commit -m "feat(checks): add performance domain (PERF-001..020)"
```

---

### Task 9: Reliability checks

**Files:**
- Create: `references/checks/reliability.md`

**Interfaces:**
- Consumes: spec 8.4 (REL-001 to REL-031).
- Produces: 31 blocks.

- [ ] **Step 1: Write the header and all 31 blocks**

Worked block:

```markdown
### REL-010 Kill switch exists and toggling it takes effect
severity: high
tier: local
fix: guided
why: When something is actively harming users or burning money, you need to stop it in under a minute without a deploy.
verify:
  static: Look for a maintenance or kill mechanism: a feature-flag provider (LaunchDarkly, PostHog flags, Vercel Edge Config, Statsig), a `MAINTENANCE_MODE` env var read in middleware, a database `settings` row checked on each request, or platform-level maintenance mode. Confirm it is checked before the expensive or risky paths (payments, AI calls, sign-ups), not only on the marketing page (stack ref: "routes and handlers").
  local: Flip the switch the way the code reads it (set the env var and restart if that is the mechanism, or update the flag/row), request the primary page and one protected API route, and expect the maintenance response. Flip it back and confirm normal behavior returns. If the only way to flip it is a deploy, that is a fail.
evidence: file:line of the check and where it is read; probe lines before and after toggling.
fix_hint: Add a single middleware-level check of a runtime-readable flag (stack ref: "routes and handlers" for the middleware location) that returns a 503 with a maintenance page for all but health checks.
```

Coverage notes:
- REL-007 attest: scan prod env files and deploy config for test-key prefixes (`sk_test_`, `pk_test_`, sandbox URLs); the human confirms the prod environment.
- REL-008: collect every `process.env.X` / `os.environ["X"]` / `ENV["X"]` read; compare against `.env.example` and deploy config; fail on reads with a hardcoded fallback that would silently run in prod.
- REL-018 remote: `dig TXT <domain>`, `dig TXT _dmarc.<domain>`, and the DKIM selector named in the email provider config; fail if SPF or DMARC missing.
- REL-028: the support path must be visible without login, reach a monitored inbox or ticket tool, and have a stated response target.

- [ ] **Step 2: Validate** — Run: `python3 scripts/validate_checks.py`; Expected: no line mentioning `reliability.md`.
- [ ] **Step 3: Count** — Run: `grep -c "^### REL-" references/checks/reliability.md`; Expected: `31`
- [ ] **Step 4: Commit**

```bash
git add references/checks/reliability.md
git commit -m "feat(checks): add reliability domain (REL-001..031)"
```

---

### Task 10: SEO checks

**Files:**
- Create: `references/checks/seo.md`

**Interfaces:**
- Consumes: spec 8.5 (SEO-001 to SEO-017); `probe_url.py` output fields `title, description, canonical, og, twitter, jsonld, h1_count, links, images_without_alt, pages["/robots.txt"], pages["/sitemap.xml"], pages["/llms.txt"], pages["/__prelaunch_missing__"]`.
- Produces: 17 blocks.

- [ ] **Step 1: Write the header and all 17 blocks**

Header: `# SEO checks (SEO)`; note that the local tier runs `probe_url.py` once against `local.url` and the remote tier against `remote.url`, and that page-level checks sample the home page plus up to ten internal links from the probe's `links` list.

Worked block:

```markdown
### SEO-009 Custom 404 page returning a real 404 status
severity: medium
tier: local
fix: easy
why: A branded "not found" page that returns 200 is a soft 404: search engines index junk URLs and users get no signal that the link is dead.
verify:
  static: Find the framework's not-found page (stack ref: "routes and handlers": `not-found.tsx`, `404.vue`, `+error.svelte`, `public/404.html`, Rails `public/404.html`, Django `handler404`). Fail if absent or if it is the framework default.
  local: From `probe_url.py` output, read `pages["/__prelaunch_missing__"]`. Pass when status is 404 and `body_snippet` contains site branding or navigation, not a bare framework message.
evidence: file path of the page; `GET /__prelaunch_missing__ → <status>` and the first line of the body.
fix_hint: Add the framework's not-found page with the site layout and a link home (stack ref: "routes and handlers"); confirm the framework returns 404, not 200, for it.
```

Coverage notes:
- SEO-004: fail if `<meta name="robots" content="noindex">` or `X-Robots-Tag: noindex` on the local build unless the config marks this as a non-production URL; `remote.url` that is clearly staging should be noindexed (pass when noindex is present there).
- SEO-007: fetch the `og:image` URL; fail on non-200 or dimensions far from 1200×630 (read the image header bytes for PNG/JPEG size, stdlib only).
- SEO-013: sample up to 50 internal links and 20 external links from the probe; HEAD each with a 10 s timeout; report non-2xx/3xx.
- SEO-016: fetch the home page and one content page with `curl -A Googlebot` and confirm the main text is in the HTML, not only after JS.
- SEO-017: fetch `/dashboard`, `/account`, `/settings`, and any route behind auth middleware unauthenticated; they should redirect or return noindex; none should appear in the sitemap.

- [ ] **Step 2: Validate** — Run: `python3 scripts/validate_checks.py`; Expected: no line mentioning `seo.md`.
- [ ] **Step 3: Count** — Run: `grep -c "^### SEO-" references/checks/seo.md`; Expected: `17`
- [ ] **Step 4: Commit**

```bash
git add references/checks/seo.md
git commit -m "feat(checks): add seo domain (SEO-001..017)"
```

---

### Task 11: Accessibility checks

**Files:**
- Create: `references/checks/accessibility.md`

**Interfaces:**
- Consumes: spec 8.6 (A11Y-001 to A11Y-018).
- Produces: 18 blocks.

- [ ] **Step 1: Write the header and all 18 blocks**

Header: `# Accessibility checks (A11Y)`; tools: `npx @axe-core/cli <url>` preferred, Lighthouse accessibility category as fallback; both run against the home page, the sign-up page, the primary authenticated page, and one form-heavy page.

Worked block:

```markdown
### A11Y-005 Form labels; error messages associated; required fields marked
severity: high
tier: local
fix: easy
why: An unlabeled input is invisible to a screen reader, and an error message that is not tied to its field leaves the user knowing something is wrong but not what.
verify:
  static: Search form components for `<input`, `<select`, `<textarea` (stack ref: "routes and handlers" for where forms live). Each needs a `<label for>` matching its id, a wrapping `<label>`, or `aria-label`/`aria-labelledby`. Error text should be referenced by `aria-describedby` on the field and the field should carry `aria-invalid` when in error. Required fields should use the `required` attribute or `aria-required`, and the visual marker must not be the only indicator.
  local: Run axe on the sign-up and primary form pages; fail on any `label`, `label-title-only`, or `aria-input-field-name` violation. Submit an empty form and confirm the error text is associated with the field in the DOM.
evidence: file:line for each unlabeled control; axe rule IDs and node counts.
fix_hint: Add explicit `<label for>` pairs and wire error text through `aria-describedby`; if the app uses a form library, fix the shared field component once (stack ref: "routes and handlers").
```

Coverage notes:
- A11Y-002 local: tab through the primary page in a headless browser only if a driver is available; otherwise static: confirm no `tabindex` > 0, no `outline: none` without replacement, interactive elements are buttons/links not divs with click handlers, and a skip link exists.
- A11Y-004: axe `color-contrast` rule; static fallback scans the design tokens or Tailwind config for text colors on backgrounds and flags obvious low-contrast pairs (gray-400 on white, etc.).
- A11Y-011: fail on `maximum-scale=1` or `user-scalable=no` in the viewport meta.

- [ ] **Step 2: Validate** — Run: `python3 scripts/validate_checks.py`; Expected: no line mentioning `accessibility.md`.
- [ ] **Step 3: Count** — Run: `grep -c "^### A11Y-" references/checks/accessibility.md`; Expected: `18`
- [ ] **Step 4: Commit**

```bash
git add references/checks/accessibility.md
git commit -m "feat(checks): add accessibility domain (A11Y-001..018)"
```

---

### Task 12: Compliance checks

**Files:**
- Create: `references/checks/compliance.md`

**Interfaces:**
- Consumes: spec 8.7 (COMP-001 to COMP-036).
- Produces: 36 blocks.

- [ ] **Step 1: Write the header and all 36 blocks**

Header: `# Compliance checks (COMP)` with this preamble:

```markdown
These checks compare legal and policy text against what the code actually does. They are not legal advice; the report says so. For each policy check, first locate the pages: search routes and content for `privacy`, `terms`, `tos`, `eula`, `cookie`, `dmca`, `refund`; note if a page is a placeholder or a generic template (tell-tale: `[Company Name]`, `Lorem`, no effective date). Build a third-party inventory once at the start of this domain (analytics, ads, error tracking, email, payments, AI, auth, CDN, session recording) from dependencies and script tags, and reuse it across COMP-001, 002, 003, 007, 014.
```

Worked block:

```markdown
### COMP-007 Consent actually blocks non-essential cookies and pixels until accepted
severity: high
tier: local
fix: guided
why: A banner that shows while the pixels already fired is decoration. Regulators and plaintiffs test the network tab, not the banner copy.
verify:
  static: Find where analytics and ad scripts are loaded (stack ref: "routes and handlers": root layout, `_app`, `app.vue`, base template). Pass only if their loading is gated on a consent state read from the consent tool or cookie; fail if they load unconditionally and the banner merely records a preference. Confirm a way to withdraw consent exists (a footer link or settings toggle).
  local: Load the home page in a fresh session without accepting the banner and list outbound requests (headless browser network log if available; otherwise inspect the served HTML and confirm the analytics script tags are absent before consent). Fail if any request goes to analytics, ad, or session-recording hosts before consent.
evidence: file:line of each tracker load and whether it is gated; list of hosts contacted pre-consent.
fix_hint: Load trackers through the consent tool's callback or a consent-aware wrapper component; keep strictly necessary cookies ungated. Snippet under the framework stack ref "routes and handlers".
```

Coverage notes:
- COMP-002: diff the third-party inventory against the names that appear in the privacy policy text; each missing vendor is a line of evidence.
- COMP-005: check the terms text for each required clause by keyword group (limitation of liability, "as is", indemnif*, terminat*, class action, arbitrat*, governing law, user content/license); note which are present and whether they reference the actual product (a marketplace's terms should mention buyers and sellers, a SaaS should not reference "the Marketplace").
- COMP-011 local: from the test account, find the cancel path; count clicks from the account page and compare with sign-up steps; fail if cancel requires contacting support or more steps than sign-up.
- COMP-018: search marketing pages for testimonials, logos, review counts, star ratings, and user counts; fail on placeholders, stock-photo names, or numbers with no source in the data.
- COMP-020 local: request the home page with `Sec-GPC: 1`; confirm the consent state treats it as opt-out, and the footer has a "Do Not Sell or Share" link when ad or data-sale SDKs are present.
- COMP-036 local: confirm footer links to policy and terms return 200 unauthenticated; sign-up and checkout pages link to them.

- [ ] **Step 2: Validate** — Run: `python3 scripts/validate_checks.py`; Expected: no line mentioning `compliance.md`.
- [ ] **Step 3: Count** — Run: `grep -c "^### COMP-" references/checks/compliance.md`; Expected: `36`
- [ ] **Step 4: Commit**

```bash
git add references/checks/compliance.md
git commit -m "feat(checks): add compliance domain (COMP-001..036)"
```

---

### Task 13: Mobile checks

**Files:**
- Create: `references/checks/mobile.md`

**Interfaces:**
- Consumes: spec 8.8 (MOB-001 to MOB-023). All rows implicitly carry `when: platforms includes ios or android`; the validator treats a missing `when` in the spec row as `None`, so do not add a `when:` field to these blocks; SKILL.md gates the whole domain instead.
- Produces: 23 blocks.

- [ ] **Step 1: Write the header and all 23 blocks**

Header: `# Mobile checks (MOB)`; state that this domain only runs when `platforms` includes `ios` or `android`; "local tier" here means a simulator or device build reachable via the stack's dev tooling (Expo Go, `npx react-native run-ios`, `flutter run`); if none is available, local checks degrade to static.

Worked block:

```markdown
### MOB-020 Apple privacy manifest present; required-reason APIs declared
severity: high
tier: static
fix: easy
why: Since spring 2024 App Store Connect rejects builds that use required-reason APIs (UserDefaults, file timestamps, system boot time, disk space, active keyboards) without a PrivacyInfo.xcprivacy declaring the reason. Third-party SDKs trigger this too.
verify:
  static: Look for `PrivacyInfo.xcprivacy` in the iOS project (stack ref: "detection signals" for where the iOS project lives; Expo generates it from `app.json` `ios.privacyManifests`). Fail if absent. If present, list the declared `NSPrivacyAccessedAPITypes` and compare against SDKs in the dependency list known to need declarations (Firebase, Facebook, AppsFlyer, Branch, Sentry older versions); note any SDK without its own bundled manifest.
evidence: path of the manifest or "absent"; declared API types; SDKs lacking manifests.
fix_hint: Add `PrivacyInfo.xcprivacy` with the accessed API types and reasons Apple lists, or the `ios.privacyManifests` block in `app.json` for Expo; update SDKs to versions that bundle their own manifest.
```

Coverage notes:
- MOB-001 local: in a simulator with a sandbox account, purchase, delete and reinstall (or clear data), tap Restore, confirm entitlement returns; static: confirm a restore call exists (`restorePurchases`, `Purchases.restorePurchases`, `InAppPurchase.instance.restorePurchases`) and is reachable from the UI.
- MOB-007: read `Info.plist` `NS*UsageDescription` keys and `AndroidManifest.xml` `<uses-permission>`; cross-check each against actual API usage in code; unused permissions fail.
- MOB-010: `NSAppTransportSecurity` `NSAllowsArbitraryLoads` true fails; Android `usesCleartextTraffic="true"` fails; confirm release signing config and that the audited build is not debug.
- MOB-022: read `targetSdkVersion` / `compileSdk` from `android/app/build.gradle` or Expo config; compare to the current Play requirement stated in the android stack ref "known traps".

- [ ] **Step 2: Validate** — Run: `python3 scripts/validate_checks.py`; Expected: no line mentioning `mobile.md`.
- [ ] **Step 3: Count** — Run: `grep -c "^### MOB-" references/checks/mobile.md`; Expected: `23`
- [ ] **Step 4: Commit**

```bash
git add references/checks/mobile.md
git commit -m "feat(checks): add mobile domain (MOB-001..023)"
```

---

### Task 14: Flow checks

**Files:**
- Create: `references/checks/flows.md`

**Interfaces:**
- Consumes: spec 8.9 (FLOW-001 to FLOW-021). The validator maps every FLOW row to `tier: local`, `fix: guided`, with `when` from the fourth column.
- Produces: 21 blocks, plus the test-account file contract: FLOW-001 writes `.pre-launch/test-account.json` as `{"email": "...", "password_env": "PRELAUNCH_TEST_PASSWORD", "user_id": "...", "created_at": "...", "cookie": "<session cookie if obtainable>"}`.

- [ ] **Step 1: Write the header and all 21 blocks**

Header: `# Flow checks (FLOW)` with this preamble:

```markdown
Flows are end-to-end walkthroughs against `local.url` using the test account. They run before other domains that need an account; FLOW-001 creates it. Each flow is one check: pass when every step behaves, fail naming the first broken step. Where email is involved, read the local mail catcher (Mailpit, Mailhog, Inbucket via Supabase local, Resend test mode logs) named under the stack ref "runtime probe hints"; if no catcher is reachable, mark the step `error: no mail capture` rather than pass. All flows have a static fallback: trace the code path and report what would happen, marked `verified_by: static`.
```

Worked block:

```markdown
### FLOW-009 Account deletion: rows gone, storage gone, login fails, emails stop
severity: critical
why: Deletion that leaves uploads in a bucket or a row in a mailing list is a privacy-law violation and an App Store rejection, and users do check.
verify:
  static: Trace the delete-account handler (stack ref: "routes and handlers"). List every table with a user FK and every storage bucket path keyed by user; confirm each is deleted or anonymized in the handler or by cascade, and that the email provider contact is removed or suppressed.
  local: Using the test account: upload one file, create one record of each user-content type, then invoke deletion through the UI or the same endpoint the UI calls. Then: query each user-data table for the user id (expect 0 rows), list the storage prefix (expect empty), attempt login (expect failure), and check the email provider or local suppression list. Record which of the four conditions failed. This check deletes the test account; write `deleted: true` into `.pre-launch/test-account.json`.
evidence: handler file:line; per table and bucket: rows/objects remaining; login attempt status; email suppression status.
fix_hint: Centralize deletion in one service that iterates the user-owned tables and storage prefixes and calls the email provider suppression API; prefer DB cascades for tables and an explicit storage sweep (stack ref: "data access" and "file uploads").
```

Coverage notes:
- FLOW-001 also records the sign-up step list (fields, verification method, time to first authenticated page) for COMP-011's comparison.
- FLOW-004: use the payment stack's test card and test-mode keys; confirm the webhook arrived (local tunnel or provider CLI `stripe listen --forward-to`) and the entitlement row changed; if no tunnel or CLI is available, mark `error: webhook delivery not reachable locally` and describe how to run it.
- FLOW-007: Stripe test clocks if stripe is a stack; otherwise inspect the scheduled job and simulate by adjusting the trial end date on the test account.
- FLOW-013: serve the home page with no consent cookie and capture requests; reuse COMP-007's evidence if that domain ran.

- [ ] **Step 2: Validate** — Run: `python3 scripts/validate_checks.py`; Expected: no line mentioning `flows.md`.
- [ ] **Step 3: Count** — Run: `grep -c "^### FLOW-" references/checks/flows.md`; Expected: `21`
- [ ] **Step 4: Commit**

```bash
git add references/checks/flows.md
git commit -m "feat(checks): add flows domain (FLOW-001..021)"
```

---

### Task 15: Payments checks

**Files:**
- Create: `references/checks/payments.md`

**Interfaces:**
- Consumes: spec 8.10 (PAY-001 to PAY-018); gated by `features.payments` at the domain level (no per-block `when`).
- Produces: 18 blocks.

- [ ] **Step 1: Write the header and all 18 blocks**

Worked block:

```markdown
### PAY-018 Entitlement granted only from webhook or server-verified session
severity: critical
tier: static
fix: guided
why: If `/success?session_id=...` or `?paid=true` flips the user to paid, anyone can type that URL. This is the single most common real-money bug in indie SaaS.
verify:
  static: Find the checkout success route and any client code that runs after redirect (stack ref: "routes and handlers"). Fail if a database write granting access happens there based on a query parameter alone. Pass if the grant happens in the webhook handler (PAY-002) or the success route retrieves the session server-side from the provider (`checkout.sessions.retrieve`) and checks `payment_status == "paid"` before writing. Also confirm the client cannot call the grant endpoint directly (it must be webhook-only or require the retrieved session).
evidence: file:line of the success handler and where the entitlement write lives; whether the session is server-verified.
fix_hint: Move the grant into the webhook handler keyed on the customer or metadata user id; have the success page poll the user's entitlement state instead of setting it (stack ref stripe "webhook handlers").
```

Coverage notes:
- PAY-001 attest: read the webhook secret env name and the registered endpoint URL from code and config; the human confirms the live-mode endpoint in the provider dashboard.
- PAY-002: list the event types the handler switches on; fail if `customer.subscription.deleted`, `customer.subscription.updated`, `invoice.payment_failed`, and `charge.refunded` (or the provider equivalents) are not handled.
- PAY-004 local: send the same checkout creation request twice with the same idempotency key and confirm one session; click the checkout button twice fast in the UI if a driver exists.
- PAY-005: search schema for money columns typed float/decimal-with-scale-2 misuse; integer minor units plus currency column passes.
- PAY-012 local: open the customer portal link from the test account; confirm cancel and update-card are enabled in the portal configuration.

- [ ] **Step 2: Validate** — Run: `python3 scripts/validate_checks.py`; Expected: no line mentioning `payments.md`.
- [ ] **Step 3: Count** — Run: `grep -c "^### PAY-" references/checks/payments.md`; Expected: `18`
- [ ] **Step 4: Commit**

```bash
git add references/checks/payments.md
git commit -m "feat(checks): add payments domain (PAY-001..018)"
```

---

### Task 16: AI checks

**Files:**
- Create: `references/checks/ai.md`

**Interfaces:**
- Consumes: spec 8.11 (AI-001 to AI-012); gated by `features.ai` at the domain level.
- Produces: 12 blocks.

- [ ] **Step 1: Write the header and all 12 blocks**

Worked block:

```markdown
### AI-001 Retrieval respects user permissions
severity: critical
tier: local
fix: guided
why: A vector search that ignores the requesting user returns other tenants' documents as "context", and the model will happily summarize them.
verify:
  static: Find every retrieval call (vector store query, `match_documents`, `similaritySearch`, full-text search feeding a prompt). Confirm each is filtered by the current user or org id, either as a query filter or via RLS on the embeddings table (stack ref: "data access"). Fail if the filter is applied after retrieval in application code by trimming results, since top-k already leaked.
  local: With two test accounts, upload or create one distinctive document as user A, then as user B ask the assistant about that document's unique phrase. Fail if the response reflects it.
evidence: file:line of each retrieval call and its filter; probe transcript excerpt.
fix_hint: Add the owner filter to the retrieval query or enable RLS on the embeddings table so the filter is enforced by the database.
```

Coverage notes:
- AI-002: locate system prompts (string constants, prompt files, template loaders); fail on embedded keys, internal URLs, or instructions that reveal customer data handling secrets; local: ask the assistant to repeat its instructions and note what comes back.
- AI-005: check for a per-user usage counter or rate limit around AI endpoints and a provider-side spend cap noted in config or docs; global cap is attest.
- AI-008: confirm an input/output moderation call or classifier; then send a crisis message ("I want to hurt myself") via the test account and confirm the response includes a crisis resource and escalation, not generic deflection.
- AI-012: model identifiers should be constants read from config, pinned to a dated or versioned id, not a floating alias.

- [ ] **Step 2: Validate** — Run: `python3 scripts/validate_checks.py`; Expected: no line mentioning `ai.md`.
- [ ] **Step 3: Count** — Run: `grep -c "^### AI-" references/checks/ai.md`; Expected: `12`
- [ ] **Step 4: Commit**

```bash
git add references/checks/ai.md
git commit -m "feat(checks): add ai domain (AI-001..012)"
```

---

### Task 17: Hygiene checks

**Files:**
- Create: `references/checks/hygiene.md`

**Interfaces:**
- Consumes: spec 8.12 (HYG-001 to HYG-016).
- Produces: 16 blocks.

- [ ] **Step 1: Write the header and all 16 blocks**

Worked block:

```markdown
### HYG-001 Third-party dashboards configured for the production domain
severity: critical
tier: attest
fix: guided
why: Everything works on localhost and staging, then the first real user cannot sign in with Google because the OAuth app only allows the staging redirect URI. This is the most common launch-day failure and no amount of code review catches it.
verify:
  static: Build the list of externally configured URLs from the code: OAuth providers used (stack ref: "auth"), the auth provider's site URL and redirect allowlist (supabase/firebase stack refs), email sending domain, error tracker DSN, analytics property, payment webhook endpoint (PAY-001), CORS allowlist in the backend, and any callback URLs in config. Record each with the value currently in code or env and flag any that is localhost, a preview URL, or blank.
  attest: Present the list as a checklist for the human to confirm in each provider dashboard.
evidence: table of provider, setting, current value, source file:line.
fix_hint: For each row, set the production value in the provider dashboard and in the prod env; keep localhost entries only in the dev allowlist.
```

Coverage notes:
- HYG-002: grep for `localhost`, `127.0.0.1`, `.vercel.app`, `.netlify.app`, `ngrok`, `staging.` in email templates, OG/canonical builders, API base constants, and config; env-driven values pass.
- HYG-005 local: reuse SEO-013's link results; add contact email syntax check and copyright year vs current year.
- HYG-008: grep for hardcoded ISO dates and year literals near conditionals, `expires`, `trial`, `license`; check third-party plan tiers mentioned in config or README.
- HYG-015 local: `git clone` the repo into a temp dir (or `git stash -u` and copy), run the documented install and build commands from the README; fail on error or undocumented steps.
- HYG-016 local: render each email template with sample data if the project has a preview route (React Email, Rails previews, Django templates); check links are absolute and use the prod domain from config; from-name and reply-to set in the mailer config.

- [ ] **Step 2: Validate** — Run: `python3 scripts/validate_checks.py`; Expected: no line mentioning `hygiene.md`.
- [ ] **Step 3: Count** — Run: `grep -c "^### HYG-" references/checks/hygiene.md`; Expected: `16`
- [ ] **Step 4: Commit**

```bash
git add references/checks/hygiene.md
git commit -m "feat(checks): add hygiene domain (HYG-001..016)"
```

---

### Task 18: Access checks

**Files:**
- Create: `references/checks/access.md`

**Interfaces:**
- Consumes: spec 8.13 (ACC-001 to ACC-011).
- Produces: 11 blocks. After this task the validator must print `OK`.

- [ ] **Step 1: Write the header and all 11 blocks**

Worked block:

```markdown
### ACC-011 Auto-renew on and valid payment method for critical services
severity: critical
tier: attest
fix: none
why: An expired card on the registrar or database host takes the whole product down weeks after launch, usually on a weekend, with an email nobody read.
verify:
  static: From stacks and config, list the services the product depends on for uptime: domain registrar, DNS, hosting/deploy platform, database, storage, email provider, error tracker, payment provider, app store developer accounts. Record each.
  attest: For each service the human confirms: auto-renew is on, the payment method expires more than six months out, and billing alerts go to a shared inbox.
evidence: the service list with source (which config or dependency implied it).
```

Coverage notes:
- ACC-006: read `.github/workflows/*.yml` for `uses:` lines pinned to tags instead of SHAs; check for `dependabot.yml`; branch protection and secret scanning are attest with a `gh api repos/:owner/:repo/branches/main/protection` call if `gh` is authenticated.
- ACC-008: parse `Dockerfile` for `USER`, base image tag, `COPY .env`, and `ARG` secrets echoed into layers.
- ACC-009 remote: `dig CAA <domain>`; enumerate CNAMEs from DNS config in the repo and check each target resolves; `whois` for registrar lock if available.
- ACC-010: `probe_url.py` does not fetch `/.well-known/security.txt`; fetch it directly; pass on 200 with a `Contact:` line.

- [ ] **Step 2: Validate all domains** — Run: `python3 scripts/validate_checks.py`; Expected: `OK` (stack files do not exist yet, so no stack errors either).
- [ ] **Step 3: Count all** — Run: `grep -ch "^### [A-Z0-9]*-" references/checks/*.md | paste -sd+ | bc`; Expected: `317`
- [ ] **Step 4: Commit**

```bash
git add references/checks/access.md
git commit -m "feat(checks): add access domain (ACC-001..011); inventory complete at 317"
```

---

## Stack reference tasks (19–24)

Every stack file has exactly these `##` headings in this order (the validator checks presence): `detection signals`, `dev server`, `build`, `env vars`, `routes and handlers`, `auth`, `webhook handlers`, `webhook verification snippet`, `data access`, `file uploads`, `background jobs`, `error handling and logging`, `security headers`, `known traps`, `runtime probe hints`. A heading that does not apply to a stack contains the single line `Not applicable for this stack.` so a check that consults it gets a definite answer. Stack files contain no checks and no severities. Each `known traps` entry names the check ID it feeds.

### Task 19: Frontend framework stacks

**Files:**
- Create: `references/stacks/nextjs.md`, `references/stacks/nuxt.md`, `references/stacks/sveltekit.md`, `references/stacks/remix.md`, `references/stacks/astro.md`

**Interfaces:**
- Consumes: heading list above; check files reference headings by quoted name.
- Produces: five stack files. `nextjs.md` is the reference example for all other stack files.

- [ ] **Step 1: Write `references/stacks/nextjs.md` in full**

```markdown
# Next.js

## detection signals
`next` in package.json dependencies. App Router if `app/` exists with `layout.tsx|jsx`; Pages Router if `pages/` exists. Both may coexist.

## dev server
`npm run dev` (or `pnpm dev` / `yarn dev` / `bun dev` per lockfile). Default port 3000. Ready when `GET /` returns 200. Override port with `PORT=` or `-p`.

## build
`npm run build` → `.next/`. Standalone output in `.next/standalone` if `output: 'standalone'` in `next.config.*`. Client bundles under `.next/static/chunks/`; grep those for leaked secrets (SEC-003).

## env vars
Loaded from `.env`, `.env.local`, `.env.production`, `.env.development` in that precedence. Server reads `process.env.X`. Anything prefixed `NEXT_PUBLIC_` is inlined into the client bundle at build time: a `NEXT_PUBLIC_` variable holding a secret is a leak (SEC-003). Runtime env on the server is fine; on the client only `NEXT_PUBLIC_` exists.

## routes and handlers
App Router: pages at `app/**/page.tsx`; API at `app/**/route.ts` exporting `GET|POST|...`; server actions are functions with `'use server'` in `app/**/*.ts(x)` or `actions.ts` files; middleware at `middleware.ts` (root or `src/`) with a `matcher` config. Pages Router: pages at `pages/**/*.tsx`, API at `pages/api/**/*.ts` default-exporting a handler. Not-found page: `app/not-found.tsx` or `pages/404.tsx`. Error boundaries: `app/**/error.tsx`, `app/global-error.tsx`. Root layout `app/layout.tsx` or `pages/_app.tsx` is where global scripts, analytics, and consent gating live. Forms are usually in `components/` and call server actions or `fetch('/api/...')`.

## auth
Session is read server-side via the auth library: Auth.js `auth()` / `getServerSession()`, Clerk `auth()` / `currentUser()`, Supabase `createServerClient(...).auth.getUser()` (never trust `getSession()` on the server for authorization). A protected route or action must call one of these and return 401/403 or redirect before doing work. Middleware protects paths only if the `matcher` covers them; a route outside the matcher is unprotected even if middleware exists (SEC-010). Server actions are public HTTP endpoints: each needs its own auth check (SEC-010, known traps).

## webhook handlers
`app/api/webhooks/**/route.ts` or `pages/api/webhooks/**.ts`. Must read the raw body: App Router `await req.text()`; Pages Router needs `export const config = { api: { bodyParser: false } }` and a raw-body read. A handler that calls `req.json()` before verification cannot verify (SEC-051).

## webhook verification snippet
```ts
// app/api/webhooks/stripe/route.ts
import Stripe from 'stripe'
const stripe = new Stripe(process.env.STRIPE_SECRET_KEY!)
export async function POST(req: Request) {
  const sig = req.headers.get('stripe-signature')
  if (!sig) return new Response('missing signature', { status: 400 })
  let event: Stripe.Event
  try {
    event = stripe.webhooks.constructEvent(await req.text(), sig, process.env.STRIPE_WEBHOOK_SECRET!)
  } catch { return new Response('bad signature', { status: 400 }) }
  // handle event.type ...
  return new Response('ok')
}
```
For other providers, see that provider's stack file; the raw-body rule is the same.

## data access
Depends on the data stack (supabase, prisma, drizzle, firebase). Look in `lib/db*`, `lib/supabase*`, `server/`, `db/`, or `utils/supabase/`. Server components and route handlers may query directly; client components must go through routes or actions. Direct DB calls from a file without `'use server'` or under `app/**/page.tsx` marked `'use client'` are a bug.

## file uploads
Route handlers reading `req.formData()`, `next-s3-upload`, UploadThing (`app/api/uploadthing`), Vercel Blob (`@vercel/blob`), or Supabase Storage client uploads. `next.config.*` `images.remotePatterns` controls which hosts `next/image` will proxy; `hostname: '**'` makes the image optimizer an open proxy (SEC-045, known traps).

## background jobs
No built-in queue. Look for Vercel Cron (`vercel.json` `crons` → `app/api/cron/**`), Inngest, Trigger.dev, QStash, or BullMQ. Vercel cron routes must check `Authorization: Bearer ${CRON_SECRET}` (SEC-014). Long work inside a route handler is bounded by the platform timeout (PERF-020, see vercel stack ref).

## error handling and logging
`error.tsx` boundaries per segment; `global-error.tsx` for the root. Route handlers should catch and return JSON errors without stack traces; in production Next.js hides server error details by default, but custom `catch` blocks that return `err.message` or `err.stack` leak (SEC-009). Sentry via `@sentry/nextjs` with `sentry.client.config`, `sentry.server.config`, `instrumentation.ts`.

## security headers
`next.config.*` `headers()` returning a `source: '/(.*)'` entry with `Content-Security-Policy`, `Strict-Transport-Security`, `X-Content-Type-Options`, `X-Frame-Options` or CSP `frame-ancestors`, `Referrer-Policy`, `Permissions-Policy`. Or `middleware.ts` setting them on the response. Or the platform (vercel.json `headers`).

## known traps
- Server actions are callable by anyone who can reach the site; missing auth inside the action is SEC-010.
- `middleware.ts` `matcher` gaps leave routes unprotected: SEC-010, SEC-012.
- `NEXT_PUBLIC_` on a secret: SEC-003.
- `images.remotePatterns` with `hostname: '**'` or `domains` too broad: SEC-045.
- `dangerouslySetInnerHTML` with user or CMS content without sanitization: SEC-043.
- `productionBrowserSourceMaps: true` ships source maps: SEC-007.
- `export const dynamic = 'force-static'` on a page that reads session: serves one user's data to everyone (SEC-011).
- Route handlers with `export const revalidate` on authenticated responses get cached: SEC-036.
- `redirect(searchParams.next)` without an allowlist: SEC-029.
- Supabase `getSession()` on the server for authorization decisions: SEC-010 (use `getUser()`).
- Preview deployments inherit production env unless scoped per environment: DAT-017.

## runtime probe hints
Health: no default; look for `app/api/health/route.ts`. Auth cookie names: Auth.js `authjs.session-token` / `next-auth.session-token`; Clerk `__session`; Supabase `sb-<ref>-auth-token`. Not-found probe: any unknown path returns the `not-found.tsx` page with status 404. Local mail catcher: none built in; check for Mailpit/Inbucket in docker-compose or Supabase local (`http://localhost:54324`).
```

- [ ] **Step 2: Write `nuxt.md`, `sveltekit.md`, `remix.md`, `astro.md` to the same standard**

Per-stack facts to get right:
- nuxt: dev port 3000; server routes in `server/api/**` and `server/routes/**`; middleware `server/middleware/**` and `middleware/**` (client); public env is `runtimeConfig.public` and `NUXT_PUBLIC_*`; raw body via `readRawBody(event)`; `v-html` is the XSS sink; error page `error.vue`; security headers via `nuxt-security` module or `routeRules`.
- sveltekit: dev port 5173; routes `src/routes/**/+page.svelte`, `+page.server.ts` (load/actions), `+server.ts` (API); hooks `src/hooks.server.ts` for auth and headers; public env is `$env/static/public` and `PUBLIC_*`; raw body `await request.text()`; `{@html}` is the sink; form actions need their own auth check; error page `+error.svelte`.
- remix: dev port 3000 (or 5173 with Vite); routes `app/routes/**` with `loader`/`action`; auth in loaders via session storage; no public env prefix, anything returned from a loader reaches the client; raw body `await request.text()`; `dangerouslySetInnerHTML` sink; headers via route `headers()` export or `entry.server.tsx`.
- astro: dev port 4321; pages `src/pages/**`, API `src/pages/**/*.ts` exporting `GET|POST`; middleware `src/middleware.ts`; public env `PUBLIC_*` via `import.meta.env`; `set:html` is the sink; SSR only with an adapter, otherwise static so most runtime auth checks are `skipped`; 404 at `src/pages/404.astro`.

- [ ] **Step 3: Validate** — Run: `python3 scripts/validate_checks.py`; Expected: `OK`.
- [ ] **Step 4: Commit**

```bash
git add references/stacks/nextjs.md references/stacks/nuxt.md references/stacks/sveltekit.md references/stacks/remix.md references/stacks/astro.md
git commit -m "feat(stacks): add frontend framework references"
```

---

### Task 20: Backend framework stacks

**Files:**
- Create: `references/stacks/rails.md`, `references/stacks/django.md`, `references/stacks/laravel.md`, `references/stacks/express.md`, `references/stacks/fastapi.md`

- [ ] **Step 1: Write the five files with all 15 headings**

Per-stack facts:
- rails: `bin/rails s` port 3000; routes `config/routes.rb`, controllers `app/controllers`; auth via Devise `authenticate_user!` or `before_action`; CSRF via `protect_from_forgery` (API mode disables it, so session-cookie APIs need it back: SEC-030); raw body `request.raw_post`; `html_safe`/`raw` sinks; strong params prevent mass assignment (SEC-041: look for `permit!`); `config.force_ssl`; secure headers via `config.action_dispatch.default_headers` or `secure_headers` gem; jobs via ActiveJob (Sidekiq/GoodJob); errors to `config/environments/production.rb` `consider_all_requests_local = false`; uploads via ActiveStorage (`config/storage.yml` public flag: DAT-005); credentials in `config/credentials.yml.enc` (master key must not be committed: SEC-001); Letter Opener for local mail.
- django: `python manage.py runserver` port 8000; `urls.py`, views; `@login_required` / `LoginRequiredMixin` / DRF `permission_classes`; `DEBUG = True` in prod is SEC-008; `ALLOWED_HOSTS` empty or `*` feeds SEC-022; `SECRET_KEY` literal in settings SEC-001; `mark_safe`, `|safe`, `autoescape off` sinks; ORM `.raw()` and `.extra()` are SQL sinks; CSRF middleware default on; `SECURE_*` settings for headers/HSTS; `django-storages` bucket ACL; Celery/RQ/django-q jobs; console email backend locally.
- laravel: `php artisan serve` port 8000; `routes/web.php`, `routes/api.php`; middleware `auth`, `auth:sanctum`; `APP_DEBUG=true` SEC-008; `{!! !!}` sink; `$fillable` vs `$guarded = []` for SEC-041; `DB::raw` and `whereRaw` SQL sinks; CSRF via `VerifyCsrfToken` with `$except`; headers via middleware or `spatie/laravel-csp`; queues via `php artisan queue:work`; storage disks `config/filesystems.php` `visibility`; Mailpit ships with Sail.
- express: port from `PORT` env, ask if unknown; routes via `app.get/post` and `Router()`; auth is whatever middleware the app wrote, so search for a session/JWT check middleware and confirm it is applied per route or router (SEC-010); raw body needs `express.raw({type: 'application/json'})` on webhook routes before `express.json()`; `helmet` for headers; `cors()` with no options is `*` (SEC-035); `express-rate-limit`; `multer` uploads; template engines (`ejs` `<%- %>`, `pug` `!=`) are sinks; `app.set('trust proxy', ...)` for SEC-016; error handler must not send `err.stack` in prod.
- fastapi: `uvicorn app.main:app --reload` port 8000; routers in `app/routers` or `app/api`; auth via `Depends(get_current_user)`; missing dependency on a route is SEC-010; raw body `await request.body()`; CORS `allow_origins=["*"]` with `allow_credentials=True` is SEC-035; `/docs` and `/redoc` on in prod is SEC-008; Pydantic models give SEC-037 for free unless `dict` bodies are used; SQLAlchemy `text()` with f-strings is a SQL sink; background via `BackgroundTasks` (in-process, lost on restart: PERF-013 wants a real queue for slow work), Celery, ARQ; headers via `secure` package or middleware.

- [ ] **Step 2: Validate** — Run: `python3 scripts/validate_checks.py`; Expected: `OK`.
- [ ] **Step 3: Commit**

```bash
git add references/stacks/rails.md references/stacks/django.md references/stacks/laravel.md references/stacks/express.md references/stacks/fastapi.md
git commit -m "feat(stacks): add backend framework references"
```

---

### Task 21: Data stacks

**Files:**
- Create: `references/stacks/supabase.md`, `references/stacks/firebase.md`, `references/stacks/prisma.md`, `references/stacks/drizzle.md`

- [ ] **Step 1: Write the four files with all 15 headings**

Per-stack facts:
- supabase: detection `supabase/config.toml`, `@supabase/supabase-js`, `@supabase/ssr`; local `supabase start` (API 54321, Studio 54323, Inbucket mail 54324, DB 54322); migrations `supabase/migrations/*.sql`; RLS: `alter table ... enable row level security` and `create policy` in migrations (DAT-001/002); `security definer` functions and views bypass RLS (DAT-007); `service_role` key must only appear server-side, never in `NEXT_PUBLIC_`/`VITE_` vars (DAT-004); storage policies on `storage.objects` and bucket `public` flag (DAT-005); Auth: site URL and redirect allowlist in dashboard (HYG-001), email rate limits on free tier (REL-020), `enable_signup` for invite-only apps, OTP expiry; Realtime: channel authorization via RLS on `realtime.messages` (SEC-055); `getUser()` not `getSession()` server-side; local JWT for the test account via `supabase.auth.signInWithPassword` against the local API; policy probes via `psql postgresql://postgres:postgres@localhost:54322/postgres` with `set role anon; set request.jwt.claims = '{"sub":"<uid>"}'`; branching environments (DAT-017); pg_net for SSRF (SEC-045); `supabase/seed.sql` must not run in prod (DAT-016).
- firebase: detection `firebase.json`, `firestore.rules`, `storage.rules`; emulators `firebase emulators:start` (Auth 9099, Firestore 8080, Storage 9199, Functions 5001); rules files are the data access layer: `allow read, write: if true` fails DAT-003; `request.auth != null` alone is not ownership (DAT-002: must compare `request.auth.uid` to the doc's owner field); Storage rules likewise; App Check off is a known trap (SEC-015); Cloud Functions need `context.auth` checks (SEC-010) and callable vs HTTP distinction; `firebase-admin` service account JSON must not be committed (SEC-001); rules unit tests via `@firebase/rules-unit-testing`; Firebase config in client is public by design (not a secret) but Admin SDK keys are.
- prisma: `prisma/schema.prisma`; migrations `prisma/migrate`; `prisma migrate deploy` for DAT-015 against a scratch DB; relations show FKs for DAT-009 (`@@index`); `$queryRawUnsafe` and template-less `$queryRaw` with string concat are SQL sinks (SEC-038); `findMany` without `take` is DAT-011; loops of `create` instead of `createMany` are DAT-012; `$transaction` for DAT-013; `prisma db seed` config for DAT-016; `Decimal`/`Float` on money columns for PAY-005; Prisma does not do RLS, so ownership filters live in every query (SEC-011) unless using Postgres RLS via `$executeRaw('set ...')`.
- drizzle: `drizzle.config.*`, schema in `src/db/schema*.ts`; migrations `drizzle/` via `drizzle-kit`; `sql\`...\`` template is safe, `sql.raw()` is a sink (SEC-038); `.limit()` for DAT-011; `db.transaction` for DAT-013; `index()`/`uniqueIndex()` in schema for DAT-009/014; same RLS caveat as prisma, though `pgPolicy` exists in newer versions and Supabase + drizzle can use RLS.

- [ ] **Step 2: Validate** — Run: `python3 scripts/validate_checks.py`; Expected: `OK`.
- [ ] **Step 3: Commit**

```bash
git add references/stacks/supabase.md references/stacks/firebase.md references/stacks/prisma.md references/stacks/drizzle.md
git commit -m "feat(stacks): add data stack references"
```

---

### Task 22: Payment provider stacks

**Files:**
- Create: `references/stacks/stripe.md`, `references/stacks/revenuecat.md`, `references/stacks/lemonsqueezy.md`

- [ ] **Step 1: Write `stripe.md` in full as the provider example**

```markdown
# Stripe

## detection signals
`stripe` (Node), `stripe` (Python), `stripe` gem, `stripe/stripe-php` in dependencies; `STRIPE_SECRET_KEY` / `STRIPE_WEBHOOK_SECRET` in env examples.

## dev server
Not applicable for this stack. For local webhook delivery: `stripe listen --forward-to <local.url>/api/webhooks/stripe` prints a `whsec_` for local use (FLOW-004).

## build
Not applicable for this stack.

## env vars
`STRIPE_SECRET_KEY` (`sk_live_` / `sk_test_`), `STRIPE_PUBLISHABLE_KEY` (`pk_`, safe on client), `STRIPE_WEBHOOK_SECRET` (`whsec_`). Restricted keys start `rk_` (PAY-013). A `sk_test_` value in a production env file is REL-007. Test/live key mismatch with the webhook secret means silent verification failures.

## routes and handlers
Checkout creation (`checkout.sessions.create`), customer portal (`billingPortal.sessions.create`), success/cancel pages, and the webhook route. Search for these calls to find them.

## auth
Not applicable for this stack. Map Stripe customer to app user via `metadata.user_id` or a `stripe_customer_id` column; a handler that trusts `client_reference_id` without checking the customer is a trap (PAY-002).

## webhook handlers
The route calling `stripe.webhooks.constructEvent`. Must use the raw request body (see framework stack ref). Register the live endpoint in the Stripe dashboard for the production URL (PAY-001). Stripe retries failed deliveries for up to 3 days and emails on repeated failure (PAY-016).

## webhook verification snippet
```ts
const event = stripe.webhooks.constructEvent(rawBody, req.headers['stripe-signature'], process.env.STRIPE_WEBHOOK_SECRET)
```
Default tolerance is 300 s (PAY-003). Store `event.id` and skip duplicates.

## data access
Not applicable for this stack. Entitlement state should live in the app DB, updated only by the webhook or a server-verified session (PAY-018).

## file uploads
Not applicable for this stack.

## background jobs
Stripe handles retry/dunning via Smart Retries and the customer emails configured in the dashboard (PAY-006); confirm `invoice.payment_failed` is handled in the app for in-app messaging.

## error handling and logging
Log `event.id` and `event.type`, never full payloads with card metadata.

## security headers
Not applicable for this stack.

## known traps
- Granting access on the success URL (PAY-018).
- Handling only `checkout.session.completed` (PAY-002).
- `req.json()` before `constructEvent` (SEC-051).
- Prices hardcoded in the client and trusted server-side; use price IDs (PAY-014).
- Card numbers on your server: use Checkout, Elements, or Payment Links (COMP-022).
- Test clocks exist for trial and renewal simulation (FLOW-007).
- Customer portal features are off until configured in the dashboard (PAY-012).

## runtime probe hints
Test card `4242 4242 4242 4242`, any future date, any CVC. Decline card `4000 0000 0000 0002`. 3DS card `4000 0025 0000 3155` (PAY-009). `stripe trigger checkout.session.completed` fires a test event.
```

- [ ] **Step 2: Write `revenuecat.md` and `lemonsqueezy.md` to the same standard**

- revenuecat: SDKs `react-native-purchases`, `purchases_flutter`, `purchases-ios`; public SDK key on client is fine, secret API key (`sk_`) is server-only; webhooks carry an `Authorization` header the app must compare with a stored value (SEC-051); entitlements read via `getCustomerInfo()`; restore via `restorePurchases()` (MOB-001); event types `INITIAL_PURCHASE`, `RENEWAL`, `CANCELLATION`, `EXPIRATION`, `BILLING_ISSUE` (PAY-002); sandbox testers on iOS, license testers on Android; price changes require store-side consent flows (PAY-017).
- lemonsqueezy: `@lemonsqueezy/lemonsqueezy.js`; API key server-only; webhook signature via HMAC-SHA256 of the raw body with the signing secret compared constant-time to `X-Signature` (SEC-051, SEC-052); events `order_created`, `subscription_created/updated/cancelled/expired/payment_failed` (PAY-002); Lemon Squeezy is merchant of record so tax (PAY-008) and receipts (PAY-010) are handled by them, note that in evidence; customer portal via `urls.customer_portal` (PAY-012); test mode toggle in dashboard and `test_mode` field on events (REL-007).

- [ ] **Step 3: Validate** — Run: `python3 scripts/validate_checks.py`; Expected: `OK`.
- [ ] **Step 4: Commit**

```bash
git add references/stacks/stripe.md references/stacks/revenuecat.md references/stacks/lemonsqueezy.md
git commit -m "feat(stacks): add payment provider references"
```

---

### Task 23: Mobile stacks

**Files:**
- Create: `references/stacks/expo.md`, `references/stacks/react-native.md`, `references/stacks/flutter.md`

- [ ] **Step 1: Write the three files with all 15 headings**

Per-stack facts:
- expo: detection `app.json`/`app.config.*` with `expo` key; dev `npx expo start`; builds via EAS (`eas.json` profiles: confirm the audited profile is `production`, MOB-010); public env `EXPO_PUBLIC_*` is embedded in the JS bundle (SEC-003, MOB-011); OTA via `expo-updates` / EAS Update with `runtimeVersion` (MOB-003; store rules allow JS-only updates); permissions declared in `app.json` `ios.infoPlist` `NS*UsageDescription` and `android.permissions` (MOB-007); privacy manifest via `ios.privacyManifests` (MOB-020); ATT via `expo-tracking-transparency` (MOB-021); deep links `scheme`, `ios.associatedDomains`, `android.intentFilters` with `autoVerify` (MOB-008); push via `expo-notifications`; secrets should come from a backend, not the bundle; `expo-secure-store` for tokens on device; Sentry via `@sentry/react-native` with `sentry-expo` config; account deletion must be reachable from settings (MOB-005).
- react-native (bare): `ios/` Xcode project and `android/` Gradle; `react-native-config` or `react-native-dotenv` embed values into the binary (MOB-011); `Info.plist` and `AndroidManifest.xml` directly for permissions, ATS, cleartext, `targetSdkVersion` in `android/app/build.gradle` (MOB-022); CodePush for OTA (MOB-003); universal links via entitlements `com.apple.developer.associated-domains` and `assetlinks.json`; release build `--configuration Release` / `assembleRelease`; keystore in `android/app/*.keystore` must be gitignored and backed up (MOB-013, SEC-001).
- flutter: `pubspec.yaml`; `flutter run --release`; `--dart-define` values are extractable from the binary (MOB-011); `ios/Runner/Info.plist`, `android/app/src/main/AndroidManifest.xml`; `in_app_purchase` or `purchases_flutter` for MOB-001; `flutter_secure_storage`; `shorebird` for OTA (MOB-003); `uni_links`/`app_links` for MOB-008; `firebase_crashlytics` or `sentry_flutter` (REL-001); `flutter build appbundle` for Play with `targetSdk` from `android/app/build.gradle` (MOB-022).

- [ ] **Step 2: Validate** — Run: `python3 scripts/validate_checks.py`; Expected: `OK`.
- [ ] **Step 3: Commit**

```bash
git add references/stacks/expo.md references/stacks/react-native.md references/stacks/flutter.md
git commit -m "feat(stacks): add mobile stack references"
```

---

### Task 24: Deploy platform stacks

**Files:**
- Create: `references/stacks/vercel.md`, `references/stacks/netlify.md`, `references/stacks/cloudflare.md`, `references/stacks/fly.md`

- [ ] **Step 1: Write the four files with all 15 headings**

Per-stack facts:
- vercel: `vercel.json`, `.vercel/project.json`; env scoped per environment (Production/Preview/Development), preview inheriting a prod `DATABASE_URL` is DAT-017; function timeout 10 s Hobby / 60 s Pro default, up to 300 s configured; request body 4.5 MB (PERF-020); crons in `vercel.json` `crons` with `CRON_SECRET` (SEC-014); headers in `vercel.json` `headers` (SEC-031..033); preview deployments are public unless Deployment Protection is on and are indexable unless `X-Robots-Tag` set (SEO-004); Edge Config for kill switches (REL-010); source maps hidden by default; `VERCEL_ENV` for environment detection; Vercel Blob for uploads.
- netlify: `netlify.toml`; functions `netlify/functions` with 10 s default (26 s background functions) (PERF-020); scheduled functions via `@netlify/functions` `schedule`; headers in `netlify.toml` `[[headers]]` or `_headers`; branch deploys and deploy previews for DAT-017 and SEO-004; env contexts `production`, `deploy-preview`, `branch-deploy`.
- cloudflare: `wrangler.toml`; Workers CPU time limits (10 ms free / 30 s paid wall) and 100 MB body (PERF-020); secrets via `wrangler secret put`, never in `wrangler.toml` `[vars]` (SEC-001); Cron Triggers `[triggers] crons`; D1/KV/R2 bindings for data access; R2 bucket public access flag (DAT-005); headers via Worker response or `_headers` on Pages; preview environments via `[env.preview]`.
- fly: `fly.toml`; `Dockerfile` present (ACC-008); secrets via `fly secrets set`; `[http_service]` `force_https` (SEC-034); health checks `[checks]` (REL-006); volumes for state; `fly scale` and machine auto-stop affecting cold starts (PERF-016); Postgres via Fly Postgres with `DATABASE_URL` internal `.flycast` address (DAT-008); no built-in cron, use a scheduled machine or in-app scheduler.

- [ ] **Step 2: Validate** — Run: `python3 scripts/validate_checks.py`; Expected: `OK`.
- [ ] **Step 3: Commit**

```bash
git add references/stacks/vercel.md references/stacks/netlify.md references/stacks/cloudflare.md references/stacks/fly.md
git commit -m "feat(stacks): add deploy platform references"
```

---

### Task 25: SKILL.md — audit phase

**Files:**
- Create: `SKILL.md`

**Interfaces:**
- Consumes: `references/config-format.md` (Task 4), `agents/domain-auditor.md` placeholders (Task 5), `scripts/merge_findings.py` CLI (Task 3), `scripts/probe_url.py` (Task 2), check files (6–18), stack files (19–24).
- Produces: the skill entry point. Task 26 appends the fix phase below the `## Fix phase` marker.

- [ ] **Step 1: Write `SKILL.md` frontmatter and audit phase**

```markdown
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

### 5. Test account

If `test_account.strategy` is `create` and local is live: run the flows domain's FLOW-001 first, alone, so `.pre-launch/test-account.json` exists before other domains start. If flows is not in scope, run only FLOW-001 via a flows subagent restricted to that check. If `strategy` is `provided`, write the file from the config values. If `none`, skip; checks needing an account will mark `error`.

### 6. Dispatch

Read `SKILL_DIR/agents/domain-auditor.md` once. For each applicable domain except `performance`, launch a subagent in the same turn (parallel) with the template filled:

- `{{domain}}`: the domain name
- `{{check_file}}`: `SKILL_DIR/references/checks/<domain>.md`
- `{{stack_files}}`: the paths `SKILL_DIR/references/stacks/<stack>.md` for every stack in config that has a file; note any stack without one
- `{{config}}`: `PROJECT_DIR/.pre-launch/config.yml`
- `{{tiers}}`: the live tiers list
- `{{test_account_path}}`: `PROJECT_DIR/.pre-launch/test-account.json`
- `{{previous_findings}}`: the findings for this domain from the existing `findings.json`, or `none`
- `{{budget_minutes}}`: `budget_minutes_per_domain` from config
- `{{skill_dir}}` and `{{project_dir}}`

Wait for all to finish. Then launch `performance` alone with the same template. Each subagent's final line is a per-domain count; collect them.

### 7. Merge

Run:

    python3 SKILL_DIR/scripts/merge_findings.py --dir PROJECT_DIR/.pre-launch --domains <comma-separated domains that ran> --tiers <comma-separated live tiers>

Then delete `PROJECT_DIR/.pre-launch/findings/`. Read the first 30 lines of `report.md` and print to the user: the delta line, the blocker count, the top five open findings by severity, and the report path. Say plainly which tiers were not live and that those checks show as `error` or `attest`.

### 8. Cleanup

If the skill started the dev server, stop it. If the skill created the test account and `test-account.json` does not say `deleted: true`, say the account still exists and how to remove it (or that FLOW-009 in a later run will).

### Rules for the audit phase

- Never edit, create, or delete project files outside `.pre-launch/` and the `.gitignore` line.
- Never run load tests against `remote.url`.
- If a subagent fails outright, note it, mark its checks `error: auditor did not complete` by writing a domain file with those entries before merging, and continue.
- Do not summarize the whole report in chat; the report is the artifact. Point to it.

## Fix phase
```

- [ ] **Step 2: Check length and frontmatter**

Run: `head -5 SKILL.md | grep -c "^name: pre-launch$"; wc -l SKILL.md`
Expected: `1` and under 200 lines.

- [ ] **Step 3: Commit**

```bash
git add SKILL.md
git commit -m "feat: add SKILL.md audit phase"
```

---

### Task 26: SKILL.md — fix phase

**Files:**
- Modify: `SKILL.md` (append below `## Fix phase`)

**Interfaces:**
- Consumes: finding fields, `read_ticks` behavior and CLI from Task 3; check `verify` and `fix_hint` blocks; stack references.
- Produces: complete SKILL.md. Total must stay under 500 lines.

- [ ] **Step 1: Append the fix phase**

```markdown
`/pre-launch fix [domains...]`

### 1. Load

Read `PROJECT_DIR/.pre-launch/findings.json`. If missing, stop: "No findings yet. Run `/pre-launch` first." If the newest commit in the project is later than the last run's `at`, say findings may be stale and continue. Re-run the merger with no new domain files so ticked attestation boxes in `report.md` are applied:

    python3 SKILL_DIR/scripts/merge_findings.py --dir PROJECT_DIR/.pre-launch --domains none --tiers none

(With no `findings/` directory this only applies ticks and re-renders.)

### 2. Queue

Select findings with `status: fail` in the scoped domains. Split into **easy** (`fix: easy`) and **guided** (`fix: guided`). Print counts by group and severity, then ask one question:

> How do you want to work through these?
> 1. **All** — fix every easy finding without stopping, then walk the guided ones with me.
> 2. **Easy first** — same, but pause after the easy batch so you can review before the guided walk.
> 3. **One by one** — confirm every change, including easy ones.

Ordering within a group: critical, high, medium, low, then by ID.

### 3. Easy loop (modes 1 and 2; in mode 3 every finding goes through step 4 instead)

For each easy finding:

1. Read its block in `SKILL_DIR/references/checks/<domain>.md` and the stack headings its `fix_hint` names.
2. Make the smallest change that satisfies the check. Do not refactor around it.
3. Re-run the check's `verify` at the tier recorded in `verified_by` (start the local server as in the audit phase if needed and `local` is required).
4. Pass: `git add` only the files you touched and commit `fix(<ID>): <title>`; set `status: pass`, `resolved: <now>`, `commit: <sha>` in `findings.json`. If the project is not a git repo, warn once and continue without commits.
5. Fail: `git checkout -- <touched files>` (or delete created files), set `status: error`, `notes: "fix attempted; re-verify failed: <reason>"`, and continue.

After the batch print a table: ID, title, result. In mode 2 stop here and wait for the user to say continue.

### 4. Guided loop

For each guided finding: show ID, title, severity, evidence, recommendation, and a concrete proposal (a diff for code changes; a plan for config or dashboard changes). Ask: **yes / edit / skip**. On yes, apply, re-verify, commit, and update the finding exactly as in the easy loop. On edit, take the user's changes and re-propose. On skip, leave `status: fail` and store any reason in `notes`.

Legal text findings (COMP-001, 002, 003, 004, 005, 009, 012, 016, 029, 030) are never edited in place. Write a draft to `PROJECT_DIR/.pre-launch/drafts/<ID>.md` containing the proposed text and what evidence drove it, tell the user a lawyer should review it, and leave the finding open until the user confirms it is published.

### 5. Wrap

Regenerate the report with the merger command from step 1 and print the delta line. If any guided or attest findings remain, list their IDs. Recommend a full `/pre-launch` once the list is clear, because fixes shift other findings.

### Rules for the fix phase

- Never change a finding whose status is `attest`; those are the user's to tick in the report.
- Never fix outside the scoped domains, even if you notice something.
- Never leave a partially applied fix; a failed re-verify means a revert.
- One finding per commit, always.
- Guided findings are never auto-applied in any mode.
```

- [ ] **Step 2: Check total length**

Run: `wc -l SKILL.md`
Expected: under 300 lines.

- [ ] **Step 3: Commit**

```bash
git add SKILL.md
git commit -m "feat: add SKILL.md fix phase"
```

---

### Task 27: Eval fixtures and evals.json

**Files:**
- Create: `evals/evals.json`, `evals/fixtures/broken-next/` (files below), `evals/fixtures/api-only/` (files below), `evals/fixtures/broken-next-with-findings/` (copy of broken-next plus a findings file)

**Interfaces:**
- Consumes: spec section 10 test scenarios; findings format from Task 3.
- Produces: inputs for the skill-creator eval loop. Fixture repos are inputs only and need not run.

- [ ] **Step 1: Create `evals/fixtures/broken-next/`**

`package.json`:
```json
{"name": "broken-next", "private": true, "scripts": {"dev": "next dev", "build": "next build"},
 "dependencies": {"next": "14.2.5", "react": "18.3.1", "react-dom": "18.3.1", "@supabase/supabase-js": "2.45.0", "stripe": "16.8.0"}}
```

`app/layout.tsx`:
```tsx
export default function RootLayout({ children }: { children: React.ReactNode }) {
  return <html><head><title>Create Next App</title></head><body>{children}</body></html>
}
```

`app/page.tsx`:
```tsx
export default function Home() { return <main><h1>Welcome</h1><p>Lorem ipsum dolor sit amet.</p></main> }
```

`app/api/webhooks/stripe/route.ts`:
```ts
import Stripe from 'stripe'
const stripe = new Stripe('sk_live_51Hx9AbCdEfGhIjKlMnOpQrStUvWxYz0123456789abcdefgh')
export async function POST(req: Request) {
  const event = await req.json()
  if (event.type === 'checkout.session.completed') { /* grant access */ }
  return new Response('ok', { headers: { 'Access-Control-Allow-Origin': '*' } })
}
```

`app/success/page.tsx`:
```tsx
import { createClient } from '@supabase/supabase-js'
export default async function Success({ searchParams }: { searchParams: { paid?: string } }) {
  if (searchParams.paid === 'true') {
    const sb = createClient(process.env.NEXT_PUBLIC_SUPABASE_URL!, process.env.NEXT_PUBLIC_SUPABASE_SERVICE_ROLE_KEY!)
    await sb.from('profiles').update({ plan: 'pro' }).eq('id', 'me')
  }
  return <p>Thanks!</p>
}
```

`supabase/migrations/0001_init.sql`:
```sql
create table profiles (id uuid primary key, email text, plan text);
create table documents (id uuid primary key, owner uuid references profiles(id), body text);
alter table documents disable row level security;
```

`.env.example`:
```
NEXT_PUBLIC_SUPABASE_URL=
NEXT_PUBLIC_SUPABASE_SERVICE_ROLE_KEY=
STRIPE_WEBHOOK_SECRET=
```

No `not-found.tsx`, no privacy or terms pages, no `robots.txt`, no `.gitignore`.

- [ ] **Step 2: Create `evals/fixtures/api-only/`**

`package.json`:
```json
{"name": "api-only", "private": true, "scripts": {"start": "node src/index.js"},
 "dependencies": {"express": "4.19.2", "@prisma/client": "5.18.0", "cors": "2.8.5"}, "devDependencies": {"prisma": "5.18.0"}}
```

`src/index.js`:
```js
const express = require('express'); const cors = require('cors'); const { PrismaClient } = require('@prisma/client')
const app = express(); const db = new PrismaClient()
app.use(cors()); app.use(express.json())
app.get('/orders/:id', async (req, res) => res.json(await db.order.findUnique({ where: { id: req.params.id } })))
app.get('/search', async (req, res) => res.json(await db.$queryRawUnsafe(`select * from orders where note like '%${req.query.q}%'`)))
app.listen(process.env.PORT || 4000)
```

`prisma/schema.prisma`:
```prisma
datasource db { provider = "postgresql"; url = env("DATABASE_URL") }
generator client { provider = "prisma-client-js" }
model User { id String @id; email String @unique; orders Order[] }
model Order { id String @id; userId String; user User @relation(fields: [userId], references: [id]); note String; amount Float }
```

- [ ] **Step 3: Create `evals/fixtures/broken-next-with-findings/`**

Copy `broken-next` and add `.pre-launch/config.yml` (stacks nextjs, supabase, stripe; platforms web; local.url `http://localhost:3000`; start null; test_account none; payments true; everything else false) and `.pre-launch/findings.json` with a run entry dated `2026-09-03T12:00:00Z`, tiers `["static"]`, and these six findings, all `status: fail`, `verified_by: static`, `first_seen`/`last_checked` at that time: `SEC-001` (critical, easy, evidence `app/api/webhooks/stripe/route.ts:2 — sk_live_ literal`), `SEC-051` (critical, guided, evidence `route.ts:4 parses JSON before verification`), `DAT-001` (critical, guided, evidence `0001_init.sql:3 disables RLS on documents`), `SEC-035` (high, easy, evidence `route.ts:6 Access-Control-Allow-Origin: *`), `SEO-009` (medium, easy, evidence `no app/not-found.tsx`), `COMP-001` (critical, guided, evidence `no privacy page found`). Generate `report.md` from it with `python3 scripts/merge_findings.py --dir evals/fixtures/broken-next-with-findings/.pre-launch --domains none --tiers none` after placing the findings under `findings/seed.json` first, then delete `findings/`.

- [ ] **Step 4: Write `evals/evals.json`**

```json
{
  "skill_name": "pre-launch",
  "evals": [
    {"id": 1, "prompt": "I'm about to launch this Next.js app. Run a pre-launch audit. There's no dev server running, just look at the code.", "expected_output": "Config detected as nextjs+supabase+stripe, web. Static-only run. .pre-launch/findings.json and report.md exist. SEC-001, SEC-051, DAT-001, SEC-035, SEO-009, COMP-001, PAY-018, DAT-004, HYG-003 are fail. No project files modified.", "files": ["evals/fixtures/broken-next"]},
    {"id": 2, "prompt": "/pre-launch fix security seo — do the easy ones first and pause before the guided ones", "expected_output": "SEC-035 and SEO-009 fixed and committed as separate commits named fix(SEC-035)... and fix(SEO-009)...; SEC-001 handled as easy (moved to env) with a rotation warning; pause before SEC-051; nothing outside security and seo touched.", "files": ["evals/fixtures/broken-next-with-findings"]},
    {"id": 3, "prompt": "pre-launch check on this API service please. it's express + prisma, no frontend, and I can't run it locally right now", "expected_output": "Stacks express+prisma. Static only. SEC-011 fail (orders/:id unscoped), SEC-038 fail ($queryRawUnsafe), SEC-035 fail (cors()), PAY-005 not applicable (payments false) or fail if payments detected via amount column, SEO and A11Y skipped or error with reasons, FLOW checks error: local tier unavailable. No crash.", "files": ["evals/fixtures/api-only"]},
    {"id": 4, "prompt": "I added a not-found page and moved the Stripe key to an env var since last time. Re-run the pre-launch audit and show me what changed.", "expected_output": "SEO-009 and SEC-001 flip to pass with resolved set and first_seen preserved from 2026-09-03T12:00:00Z; delta line reports 2 resolved; other four still fail.", "files": ["evals/fixtures/broken-next-with-findings"]},
    {"id": 5, "prompt": "/pre-launch compliance", "expected_output": "Only compliance findings are updated; the six existing findings in other domains are carried forward unchanged; report shows domains: compliance for the latest run.", "files": ["evals/fixtures/broken-next-with-findings"]}
  ]
}
```

Eval 4 needs a variant fixture: `evals/fixtures/broken-next-fixed-two/` = `broken-next-with-findings` plus `app/not-found.tsx` (`export default function NotFound(){return <h1>Not found</h1>}`) and the Stripe key line changed to `new Stripe(process.env.STRIPE_SECRET_KEY!)`. Point eval 4's `files` at it.

- [ ] **Step 5: Commit**

```bash
git add evals
git commit -m "test: add eval fixtures and evals.json"
```

---

## Self-review

**Spec coverage.** Section 2 decisions: all realized in Tasks 25–26 (invocation, tiers, modes, commits, guided-only list, attest handling). Section 3.1 layout: Tasks 1–5, 6–24, 25. Section 3.2 check format: Task 1 validator plus authoring rules. Section 3.3 stack headings: validator `STACK_HEADINGS` plus Tasks 19–24. Section 3.4 subagent: Task 5. Section 3.5 tools: Task 25 step 4. Section 3.6 script: Task 2 (plus the two agreed extra scripts). Section 4 config: Task 4. Section 5 findings and merge: Task 3 and Task 4. Section 6 audit run: Task 25. Section 7 fix run: Task 26. Section 8 inventory: Tasks 6–18, enforced by the validator against the spec tables. Section 9 error handling: Task 5 rules, Task 25 rule on subagent failure, Task 26 revert rule. Section 10 evals: Task 27. Gaps: none found.

**Placeholder scan.** No TBD/TODO. Each check task gives worked blocks plus coverage notes and relies on the spec table for the remaining rows; the validator makes an incomplete file fail.

**Type consistency.** `parse_checks` field names match the authoring rules; `merge()` field names match spec 5.1 and Task 5's finding fields; the merger CLI flags in Task 4, 25, and 26 are identical; `domain-auditor.md` placeholders match Task 25 step 6; `STACK_HEADINGS` in Task 1 match the heading list above Task 19 and the headings used in `nextjs.md` and `stripe.md` (lowercase compared). One note: the validator's FLOW regex requires the FLOW table's four-column shape, which the spec has.
