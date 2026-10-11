import json

from review_agent.rag.owasp_loader import load_owasp_rules


def test_owasp_loader_preserves_heading_and_provenance(tmp_path):
    row = {
        "chunk_id": "owasp-cheatsheet:SQL:abc:0:123",
        "rule_id": "OWASP-CS-SQL", "title": "SQL Security",
        "section_type": "guidance", "text": "Use parameters.",
        "heading_path": ["SQL Security", "Defense Option 1"],
        "source_version": "a" * 40, "source_url": "https://example.test/sql.md",
        "source_file_sha256": "b" * 64, "chunk_sha256": "c" * 64,
    }
    path = tmp_path / "owasp.jsonl"
    path.write_text(json.dumps(row) + "\n", encoding="utf-8")
    rules = load_owasp_rules(path)
    assert len(rules) == 1
    assert rules[0].heading_path == ("SQL Security", "Defense Option 1")
    assert "Defense Option 1" in rules[0].text
    assert rules[0].source_chunk_sha256 == "c" * 64
