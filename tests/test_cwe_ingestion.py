from __future__ import annotations

from pathlib import Path

from review_agent.rag.ingestion.cwe_parser import parse_cwe_xml
from review_agent.rag.ingestion.models import SourceSnapshot


XML = """<?xml version="1.0"?>
<Weakness_Catalog xmlns="http://cwe.mitre.org/cwe-7" Version="4.20">
  <Weaknesses>
    <Weakness ID="89" Name="SQL Injection">
      <Description>Untrusted input changes an SQL command.</Description>
      <Extended_Description><xhtml:p xmlns:xhtml="http://www.w3.org/1999/xhtml">Extended text.</xhtml:p></Extended_Description>
      <Detection_Methods><Detection_Method><Method>Automated Analysis</Method><Description>Find string-built SQL.</Description></Detection_Method></Detection_Methods>
      <Potential_Mitigations><Mitigation><Phase>Implementation</Phase><Description>Use parameterized queries.</Description></Mitigation></Potential_Mitigations>
      <Demonstrative_Examples><Demonstrative_Example><Intro_Text>Bad example</Intro_Text><Example_Code Language="Python">execute(query + user)</Example_Code></Demonstrative_Example></Demonstrative_Examples>
    </Weakness>
  </Weaknesses>
</Weakness_Catalog>
"""


def snapshot() -> SourceSnapshot:
    return SourceSnapshot(
        source_id="mitre-cwe",
        source_version="4.20",
        source_url="https://cwe.mitre.org/data/xml/cwec_latest.xml.zip",
        source_file="cwec_v4.20.xml",
        source_file_sha256="a" * 64,
        retrieved_at="2026-09-16T00:00:00Z",
        license_name="CWE Terms of Use",
        license_url="https://cwe.mitre.org/about/termsofuse.html",
    )


def test_cwe_parser_creates_field_level_traceable_chunks(tmp_path: Path):
    path = tmp_path / "cwe.xml"
    path.write_text(XML, encoding="utf-8")
    chunks = parse_cwe_xml(path, snapshot())
    assert {chunk.section_type for chunk in chunks} == {"description", "detection", "mitigation", "example"}
    assert all(chunk.rule_id == "CWE-89" for chunk in chunks)
    assert all(chunk.source.source_file_sha256 == "a" * 64 for chunk in chunks)
    assert len({chunk.chunk_id for chunk in chunks}) == len(chunks)


def test_cwe_chunk_hash_is_stable(tmp_path: Path):
    path = tmp_path / "cwe.xml"
    path.write_text(XML, encoding="utf-8")
    first = parse_cwe_xml(path, snapshot())
    second = parse_cwe_xml(path, snapshot())
    assert [chunk.chunk_sha256 for chunk in first] == [chunk.chunk_sha256 for chunk in second]
