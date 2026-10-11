"""规则知识单据与稳定内容哈希。"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any


def canonical_json(value: dict[str, Any]) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


@dataclass(frozen=True)
class RuleDocument:
    rule_id: str
    title: str
    text: str
    languages: tuple[str, ...]
    category: str
    severity: str
    source: str
    source_url: str
    knowledge_version: str = "v1"
    enabled: bool = True
    chunk_id: str = ""
    section_type: str = ""
    source_version: str = ""
    source_file_sha256: str = ""
    source_chunk_sha256: str = ""
    heading_path: tuple[str, ...] = ()

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "RuleDocument":
        required = ("rule_id", "title", "text", "languages", "category", "severity", "source")
        missing = [key for key in required if not data.get(key)]
        if missing:
            raise ValueError(f"规则缺少字段: {', '.join(missing)}")
        languages = data["languages"]
        if not isinstance(languages, list) or not all(isinstance(v, str) and v for v in languages):
            raise ValueError("languages 必须是非空字符串数组")
        return cls(
            rule_id=str(data["rule_id"]),
            title=str(data["title"]),
            text=str(data["text"]),
            languages=tuple(languages),
            category=str(data["category"]),
            severity=str(data["severity"]),
            source=str(data["source"]),
            source_url=str(data.get("source_url") or ""),
            knowledge_version=str(data.get("knowledge_version") or "v1"),
            enabled=bool(data.get("enabled", True)),
            chunk_id=str(data.get("chunk_id") or ""),
            section_type=str(data.get("section_type") or ""),
            source_version=str(data.get("source_version") or ""),
            source_file_sha256=str(data.get("source_file_sha256") or ""),
            source_chunk_sha256=str(data.get("source_chunk_sha256") or ""),
            heading_path=tuple(str(value) for value in (data.get("heading_path") or [])),
        )

    def hash_payload(self) -> dict[str, Any]:
        return {
            "rule_id": self.rule_id,
            "title": self.title,
            "text": self.text,
            "languages": list(self.languages),
            "category": self.category,
            "severity": self.severity,
            "source": self.source,
            "source_url": self.source_url,
            "knowledge_version": self.knowledge_version,
            "enabled": self.enabled,
            "chunk_id": self.chunk_id,
            "section_type": self.section_type,
            "source_version": self.source_version,
            "source_file_sha256": self.source_file_sha256,
            "source_chunk_sha256": self.source_chunk_sha256,
            "heading_path": list(self.heading_path),
        }

    @property
    def content_sha256(self) -> str:
        return hashlib.sha256(canonical_json(self.hash_payload()).encode("utf-8")).hexdigest()

    @property
    def embedding_text(self) -> str:
        return (
            f"Rule: {self.rule_id}\nTitle: {self.title}\nCategory: {self.category}\n"
            f"Severity: {self.severity}\nLanguages: {', '.join(self.languages)}\n{self.text}"
        )

    def to_payload(self, *, model: str, dimensions: int) -> dict[str, Any]:
        return {
            **self.hash_payload(),
            "content_sha256": self.content_sha256,
            "embedding_model": model,
            "embedding_dimensions": dimensions,
        }


@dataclass(frozen=True)
class RetrievedRule:
    rule_id: str
    title: str
    text: str
    score: float
    content_sha256: str
    source: str
    source_url: str
    category: str
    severity: str
    knowledge_version: str
    chunk_id: str = ""
    section_type: str = ""
    source_version: str = ""
    source_file_sha256: str = ""
    source_chunk_sha256: str = ""
    heading_path: tuple[str, ...] = ()
