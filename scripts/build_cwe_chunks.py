"""将已快照的 MITRE CWE XML 转换为可追溯 JSONL Chunk。"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from review_agent.jsonutil import to_json_line
from review_agent.rag.ingestion.cwe_parser import parse_cwe_xml
from review_agent.rag.ingestion.models import SourceSnapshot


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("snapshot_dir", help="例如 knowledge/raw/cwe/4.20")
    parser.add_argument("--output", default="knowledge/normalized/cwe.jsonl")
    args = parser.parse_args()
    snapshot_dir = Path(args.snapshot_dir)
    manifest = json.loads((snapshot_dir / "manifest.json").read_text(encoding="utf-8"))
    xml_path = snapshot_dir / manifest["xml_file"]
    snapshot = SourceSnapshot(
        source_id=manifest["source_id"],
        source_version=manifest["source_version"],
        source_url=manifest["source_url"],
        source_file=str(xml_path),
        source_file_sha256=manifest["xml_sha256"],
        retrieved_at=manifest["retrieved_at"],
        license_name=manifest["license"],
        license_url=manifest["license_url"],
    )
    chunks = parse_cwe_xml(xml_path, snapshot)
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text("".join(to_json_line(chunk.to_dict()) + "\n" for chunk in chunks), encoding="utf-8")
    rules = len({chunk.rule_id for chunk in chunks})
    print(f"CWE {snapshot.source_version}: {rules} rules, {len(chunks)} chunks -> {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
