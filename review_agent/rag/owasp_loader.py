"""将 OWASP Cheat Sheet JSONL 转换为向量库规则文档。"""

from __future__ import annotations

import json
from pathlib import Path

from .cwe_loader import DEFAULT_LANGUAGES
from .models import RuleDocument


def load_owasp_rules(
    chunks_path: str | Path,
    *,
    knowledge_version: str = "v1",
) -> list[RuleDocument]:
    rules: list[RuleDocument] = []
    seen: set[str] = set()
    with Path(chunks_path).open(encoding="utf-8") as stream:
        for line_number, line in enumerate(stream, start=1):
            if not line.strip():
                continue
            try:
                item = json.loads(line)
            except json.JSONDecodeError as err:
                raise ValueError(f"OWASP JSONL 第 {line_number} 行格式错误") from err
            chunk_id = str(item.get("chunk_id") or "")
            if not chunk_id or chunk_id in seen:
                raise ValueError(f"OWASP chunk_id 缺失或重复: {chunk_id!r}")
            seen.add(chunk_id)
            heading_path = tuple(str(value) for value in (item.get("heading_path") or []))
            section = " > ".join(heading_path)
            text = f"Section: {section}\n\n{item['text']}" if section else str(item["text"])
            rules.append(
                RuleDocument(
                    rule_id=str(item["rule_id"]),
                    title=str(item["title"]),
                    text=text,
                    languages=DEFAULT_LANGUAGES,
                    category="security",
                    severity="reference",
                    source="OWASP Cheat Sheet Series",
                    source_url=str(item["source_url"]),
                    knowledge_version=knowledge_version,
                    chunk_id=chunk_id,
                    section_type=str(item["section_type"]),
                    source_version=str(item["source_version"]),
                    source_file_sha256=str(item["source_file_sha256"]),
                    source_chunk_sha256=str(item["chunk_sha256"]),
                    heading_path=heading_path,
                )
            )
    return rules
