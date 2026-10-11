"""面向安全文档的 Markdown 标题级切分，保留代码块完整性。"""

from __future__ import annotations

import hashlib
import re
from pathlib import Path

from .models import KnowledgeChunk, SourceSnapshot
from .normalize import normalize_text


HEADING = re.compile(r"^(#{1,6})\s+(.+?)\s*#*\s*$")
FENCE = re.compile(r"^\s*(```|~~~)")


def _blocks(lines: list[str]) -> list[str]:
    blocks: list[str] = []
    current: list[str] = []
    fence_marker = ""
    for line in lines:
        match = FENCE.match(line)
        if match:
            marker = match.group(1)
            if not fence_marker:
                fence_marker = marker
            elif marker == fence_marker:
                fence_marker = ""
        if not line.strip() and not fence_marker:
            if current:
                blocks.append("\n".join(current).strip())
                current = []
        else:
            current.append(line.rstrip())
    if current:
        blocks.append("\n".join(current).strip())
    return [block for block in blocks if block]


def _pack(blocks: list[str], max_chars: int) -> list[str]:
    packed: list[str] = []
    current = ""
    for block in blocks:
        candidate = f"{current}\n\n{block}" if current else block
        if current and len(candidate) > max_chars:
            packed.append(current)
            current = block
        else:
            current = candidate
    if current:
        packed.append(current)
    return packed


def parse_markdown(
    path: str | Path,
    snapshot: SourceSnapshot,
    *,
    max_chars: int = 3200,
) -> list[KnowledgeChunk]:
    if max_chars < 500:
        raise ValueError("max_chars 不能小于 500")
    file_path = Path(path)
    lines = file_path.read_text(encoding="utf-8-sig").splitlines()
    title = file_path.stem.replace("_", " ")
    headings: list[str] = []
    section_lines: list[str] = []
    sections: list[tuple[tuple[str, ...], list[str]]] = []
    fence_marker = ""

    def flush() -> None:
        nonlocal section_lines
        if section_lines:
            sections.append((tuple(headings) or (title,), section_lines))
            section_lines = []

    for line in lines:
        fence = FENCE.match(line)
        if fence:
            marker = fence.group(1)
            if not fence_marker:
                fence_marker = marker
            elif marker == fence_marker:
                fence_marker = ""
            section_lines.append(line)
            continue
        heading = HEADING.match(line) if not fence_marker else None
        if heading:
            flush()
            level = len(heading.group(1))
            name = normalize_text(heading.group(2))
            headings[:] = headings[: level - 1]
            headings.append(name)
            if level == 1:
                title = name
        else:
            section_lines.append(line)
    flush()

    chunks: list[KnowledgeChunk] = []
    rule_id = f"OWASP-CS-{file_path.stem}"
    ordinal = 0
    for heading_path, content_lines in sections:
        for text in _pack(_blocks(content_lines), max_chars):
            if not text.strip():
                continue
            path_hash = hashlib.sha256(" > ".join(heading_path).encode("utf-8")).hexdigest()[:12]
            chunks.append(
                KnowledgeChunk(
                    chunk_id=(
                        f"owasp-cheatsheet:{file_path.stem}:{path_hash}:{ordinal}:"
                        f"{snapshot.source_version[:12]}"
                    ),
                    rule_id=rule_id,
                    title=title,
                    section_type="guidance",
                    ordinal=ordinal,
                    text=text,
                    heading_path=heading_path,
                    source=snapshot,
                )
            )
            ordinal += 1
    return chunks
