"""从受控 JSON 文件加载审查规则。"""

from __future__ import annotations

import json
from pathlib import Path

from .models import RuleDocument


def load_rules(path: str | Path, *, knowledge_version: str | None = None) -> list[RuleDocument]:
    file_path = Path(path).resolve()
    data = json.loads(file_path.read_text(encoding="utf-8"))
    if not isinstance(data, list):
        raise ValueError("规则文件必须是 JSON 数组")
    rules = [RuleDocument.from_dict(item) for item in data]
    if knowledge_version is not None:
        rules = [rule for rule in rules if rule.knowledge_version == knowledge_version]
    ids = [(rule.rule_id, rule.knowledge_version) for rule in rules]
    if len(ids) != len(set(ids)):
        raise ValueError("同一知识版本中 rule_id 必须唯一")
    return rules
