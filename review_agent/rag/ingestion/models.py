from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any


def canonical_json(value: dict[str, Any]) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


@dataclass(frozen=True)
class SourceSnapshot:
    source_id: str
    source_version: str
    source_url: str
    source_file: str
    source_file_sha256: str
    retrieved_at: str
    license_name: str
    license_url: str


@dataclass(frozen=True)
class KnowledgeChunk:
    chunk_id: str
    rule_id: str
    title: str
    section_type: str
    ordinal: int
    text: str
    heading_path: tuple[str, ...]
    source: SourceSnapshot

    @property
    def chunk_sha256(self) -> str:
        value = {
            "rule_id": self.rule_id,
            "title": self.title,
            "section_type": self.section_type,
            "ordinal": self.ordinal,
            "text": self.text,
            "heading_path": list(self.heading_path),
            "source_id": self.source.source_id,
            "source_version": self.source.source_version,
            "source_file_sha256": self.source.source_file_sha256,
        }
        return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()

    def to_dict(self) -> dict[str, Any]:
        return {
            "chunk_id": self.chunk_id,
            "rule_id": self.rule_id,
            "title": self.title,
            "section_type": self.section_type,
            "ordinal": self.ordinal,
            "text": self.text,
            "heading_path": list(self.heading_path),
            "chunk_sha256": self.chunk_sha256,
            "source_id": self.source.source_id,
            "source_version": self.source.source_version,
            "source_url": self.source.source_url,
            "source_file": self.source.source_file,
            "source_file_sha256": self.source.source_file_sha256,
            "retrieved_at": self.source.retrieved_at,
            "license": self.source.license_name,
            "license_url": self.source.license_url,
        }
