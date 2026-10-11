from __future__ import annotations

import re
import xml.etree.ElementTree as ET


def normalize_text(text: str) -> str:
    lines = [re.sub(r"[ \t]+", " ", line).strip() for line in text.replace("\r\n", "\n").split("\n")]
    compact: list[str] = []
    for line in lines:
        if line or (compact and compact[-1]):
            compact.append(line)
    return "\n".join(compact).strip()


def element_text(element: ET.Element | None) -> str:
    if element is None:
        return ""
    return normalize_text(" ".join(part for part in element.itertext() if part))
