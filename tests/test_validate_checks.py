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

FLOW_SPEC = textwrap.dedent("""
    ### 8.9 User flows (FLOW)
    | ID | Check | Sev | when |
    |---|---|---|---|
    | FLOW-001 | Fresh sign-up end-to-end; verification email received | C | |
    | FLOW-004 | Test-mode checkout → webhook received → entitlement granted | C | features.payments |
""")

def test_spec_ids_parses_flow_rows_with_empty_when():
    ids = spec_ids(FLOW_SPEC)
    assert ids["FLOW-001"]["tier"] == "local" and ids["FLOW-001"]["fix"] == "guided"
    assert ids["FLOW-001"]["when"] is None
    assert ids["FLOW-004"]["tier"] == "local" and ids["FLOW-004"]["fix"] == "guided"
    assert ids["FLOW-004"]["when"] == "features.payments"
