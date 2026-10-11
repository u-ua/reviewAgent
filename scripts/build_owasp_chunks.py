"""从固定 OWASP Markdown 快照生成可追溯 JSONL。"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from review_agent.rag.ingestion.markdown_parser import parse_markdown
from review_agent.rag.ingestion.models import SourceSnapshot


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("snapshot_dir")
    parser.add_argument("--output", default="knowledge/normalized/owasp_cheatsheets.jsonl")
    parser.add_argument("--max-chars", type=int, default=3200)
    args = parser.parse_args()

    snapshot_dir = Path(args.snapshot_dir)
    manifest = json.loads((snapshot_dir / "manifest.json").read_text(encoding="utf-8"))
    chunks = []
    for record in manifest["files"]:
        source = SourceSnapshot(
            source_id=manifest["source_id"],
            source_version=manifest["source_version"],
            source_url=record["url"],
            source_file=str(snapshot_dir / record["file"]),
            source_file_sha256=record["sha256"],
            retrieved_at=manifest["retrieved_at"],
            license_name=manifest["license"],
            license_url=manifest["license_url"],
        )
        chunks.extend(parse_markdown(snapshot_dir / record["file"], source, max_chars=args.max_chars))

    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", encoding="utf-8", newline="\n") as stream:
        for chunk in chunks:
            stream.write(json.dumps(chunk.to_dict(), ensure_ascii=False) + "\n")
    print(f"OWASP {manifest['source_version'][:12]}: {len(manifest['files'])} files, {len(chunks)} chunks -> {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
