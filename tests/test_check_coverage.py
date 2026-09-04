import sys, pathlib, json
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "scripts"))
from check_coverage import missing_ids

CHECKS = "### FLOW-001 A\nseverity: high\n\n### FLOW-002 B\nseverity: high\n\n### FLOW-003 C\nseverity: low\n"


def test_missing_ids_across_split_files(tmp_path):
    (tmp_path / "checks").mkdir(); (tmp_path / "checks" / "flows.md").write_text(CHECKS)
    fd = tmp_path / "findings"; fd.mkdir()
    (fd / "flows-1.json").write_text(json.dumps([{"id": "FLOW-001", "status": "pass"}]))
    (fd / "flows.json").write_text(json.dumps([{"id": "FLOW-003", "status": "skipped"}]))
    (fd / "broken.json").write_text("{not json")
    assert missing_ids(fd, tmp_path / "checks", ["flows", "nosuch"]) == {"flows": ["FLOW-002"], "nosuch": []}
