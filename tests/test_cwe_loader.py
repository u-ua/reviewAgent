from __future__ import annotations

import json

from review_agent.rag.cwe_loader import load_cwe_rules


def test_cwe_loader_filters_scope_and_preserves_provenance(tmp_path):
    scope = tmp_path / "scope.json"
    scope.write_text(json.dumps({"groups": {"injection": ["CWE-89"]}}), encoding="utf-8")
    chunks = tmp_path / "chunks.jsonl"
    rows = [
        {
            "chunk_id": "mitre-cwe:CWE-89:mitigation:0:4.20",
            "rule_id": "CWE-89", "title": "SQL Injection", "section_type": "mitigation",
            "text": "Use parameterized queries.", "source_version": "4.20",
            "source_file_sha256": "a" * 64, "chunk_sha256": "b" * 64,
        },
        {
            "chunk_id": "mitre-cwe:CWE-79:mitigation:0:4.20",
            "rule_id": "CWE-79", "title": "XSS", "section_type": "mitigation",
            "text": "Encode output.", "source_version": "4.20",
            "source_file_sha256": "a" * 64, "chunk_sha256": "c" * 64,
        },
    ]
    chunks.write_text("\n".join(json.dumps(row) for row in rows), encoding="utf-8")

    rules = load_cwe_rules(chunks, scope)
    assert len(rules) == 1
    assert rules[0].rule_id == "CWE-89"
    assert rules[0].chunk_id.endswith(":4.20")
    assert rules[0].source_chunk_sha256 == "b" * 64
    assert "python" in rules[0].languages
