from review_agent.rag.ingestion.markdown_parser import parse_markdown
from review_agent.rag.ingestion.models import SourceSnapshot


def _snapshot():
    return SourceSnapshot(
        source_id="owasp-cheatsheet-series", source_version="a" * 40,
        source_url="https://example.test/doc.md", source_file="doc.md",
        source_file_sha256="b" * 64, retrieved_at="2026-09-16T00:00:00Z",
        license_name="CC BY-SA 4.0", license_url="https://example.test/license",
    )


def test_markdown_parser_splits_by_heading_and_ignores_headings_in_fences(tmp_path):
    path = tmp_path / "SQL_Cheat_Sheet.md"
    path.write_text(
        "# SQL Security\n\nIntro.\n\n## Parameterization\n\nUse parameters.\n\n"
        "```python\n# not a heading\nexecute(sql)\n```\n",
        encoding="utf-8",
    )
    chunks = parse_markdown(path, _snapshot(), max_chars=500)
    assert len(chunks) == 2
    assert chunks[0].heading_path == ("SQL Security",)
    assert chunks[1].heading_path == ("SQL Security", "Parameterization")
    assert "# not a heading" in chunks[1].text
    assert chunks[1].source.source_file_sha256 == "b" * 64
