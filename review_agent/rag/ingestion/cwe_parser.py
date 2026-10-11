"""MITRE CWE XML 的字段级语义切分器。"""

from __future__ import annotations

import xml.etree.ElementTree as ET
from pathlib import Path

from .models import KnowledgeChunk, SourceSnapshot
from .normalize import element_text


def _namespace(root: ET.Element) -> str:
    if root.tag.startswith("{"):
        return root.tag[1:].split("}", 1)[0]
    return ""


def _tag(ns: str, name: str) -> str:
    return f"{{{ns}}}{name}" if ns else name


def _children_text(parent: ET.Element, path: str, ns: str) -> list[str]:
    values: list[str] = []
    for element in parent.findall(path, {"cwe": ns} if ns else {}):
        text = element_text(element)
        if text:
            values.append(text)
    return values


def parse_cwe_xml(path: str | Path, snapshot: SourceSnapshot) -> list[KnowledgeChunk]:
    root = ET.parse(path).getroot()
    ns = _namespace(root)
    prefix = "cwe:" if ns else ""
    weaknesses = root.findall(f".//{prefix}Weakness", {"cwe": ns} if ns else {})
    chunks: list[KnowledgeChunk] = []

    for weakness in weaknesses:
        cwe_id = f"CWE-{weakness.attrib['ID']}"
        title = weakness.attrib.get("Name", cwe_id)
        sections: list[tuple[str, list[str]]] = [
            (
                "description",
                _children_text(weakness, f"./{prefix}Description", ns)
                + _children_text(weakness, f"./{prefix}Extended_Description", ns),
            ),
            (
                "consequence",
                _children_text(
                    weakness,
                    f"./{prefix}Common_Consequences/{prefix}Consequence",
                    ns,
                ),
            ),
            (
                "detection",
                _children_text(
                    weakness,
                    f"./{prefix}Detection_Methods/{prefix}Detection_Method",
                    ns,
                ),
            ),
            (
                "mitigation",
                _children_text(
                    weakness,
                    f"./{prefix}Potential_Mitigations/{prefix}Mitigation",
                    ns,
                ),
            ),
            (
                "example",
                _children_text(
                    weakness,
                    f"./{prefix}Demonstrative_Examples/{prefix}Demonstrative_Example",
                    ns,
                ),
            ),
        ]
        for section_type, texts in sections:
            for ordinal, text in enumerate(texts):
                chunks.append(
                    KnowledgeChunk(
                        chunk_id=(
                            f"mitre-cwe:{cwe_id}:{section_type}:{ordinal}:"
                            f"{snapshot.source_version}"
                        ),
                        rule_id=cwe_id,
                        title=title,
                        section_type=section_type,
                        ordinal=ordinal,
                        text=text,
                        heading_path=(cwe_id, title, section_type),
                        source=snapshot,
                    )
                )
    return chunks
