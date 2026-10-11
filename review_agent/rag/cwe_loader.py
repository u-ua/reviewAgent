"""将规范化 CWE 分块筛选并转换为可入库的规则文档。"""

from __future__ import annotations

import json
from pathlib import Path

from .models import RuleDocument


DEFAULT_LANGUAGES = (
    "python", "javascript", "typescript", "java", "csharp", "go",
    "rust", "php", "ruby", "c", "cpp",
)


def load_cwe_scope(path: str | Path) -> set[str]:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    groups = data.get("groups")
    if not isinstance(groups, dict):
        raise ValueError("CWE scope 必须包含 groups 对象")
    ids = {str(cwe_id) for values in groups.values() for cwe_id in values}
    if not ids or any(not value.startswith("CWE-") for value in ids):
        raise ValueError("CWE scope 中必须使用 CWE-<number> 标识")
    return ids


def load_cwe_rules(
    chunks_path: str | Path,
    scope_path: str | Path,
    *,
    knowledge_version: str = "v1",
    sections: set[str] | None = None,
) -> list[RuleDocument]:
    allowed_ids = load_cwe_scope(scope_path)
    allowed_sections = sections or {"description", "consequence", "detection", "mitigation", "example"}
    rules: list[RuleDocument] = []
    seen_chunks: set[str] = set()

    with Path(chunks_path).open(encoding="utf-8") as stream:
        for line_number, line in enumerate(stream, start=1):
            if not line.strip():
                continue
            try:
                item = json.loads(line)
            except json.JSONDecodeError as err:
                raise ValueError(f"CWE JSONL 第 {line_number} 行格式错误") from err
            if item.get("rule_id") not in allowed_ids or item.get("section_type") not in allowed_sections:
                continue
            chunk_id = str(item.get("chunk_id") or "")
            if not chunk_id or chunk_id in seen_chunks:
                raise ValueError(f"CWE chunk_id 缺失或重复: {chunk_id!r}")
            seen_chunks.add(chunk_id)
            rule_id = str(item["rule_id"])
            rules.append(
                RuleDocument(
                    rule_id=rule_id,
                    title=str(item["title"]),
                    text=str(item["text"]),
                    languages=DEFAULT_LANGUAGES,
                    category="security",
                    severity="reference",
                    source="MITRE CWE",
                    source_url=f"https://cwe.mitre.org/data/definitions/{rule_id.removeprefix('CWE-')}.html",
                    knowledge_version=knowledge_version,
                    chunk_id=chunk_id,
                    section_type=str(item["section_type"]),
                    source_version=str(item["source_version"]),
                    source_file_sha256=str(item["source_file_sha256"]),
                    source_chunk_sha256=str(item["chunk_sha256"]),
                )
            )
    return rules
