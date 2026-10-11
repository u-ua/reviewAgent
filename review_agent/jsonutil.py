"""JSON 工具（对应 src/json.ts）：流水账的一行一行、从模型文本容错抽取 JSON。"""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from typing import Any


def to_json_line(value: Any) -> str:
    """把任意值序列化成一行 JSON（不带换行，调用方负责 \\n）。"""
    return json.dumps(value, ensure_ascii=False)


def extract_json_object(text: str) -> dict[str, Any]:
    """从模型输出文本里容错抽取一个 JSON 对象。

    依次尝试：整体 JSON.parse → 去除代码围栏 → 从第一个 { 到匹配的最后一个 } 截取。
    抽不出来抛 ValueError。
    """
    trimmed = text.strip()
    if not trimmed:
        raise ValueError("extractJsonObject: 空文本")

    # 1) 整体就是 JSON
    try:
        parsed = json.loads(trimmed)
        if isinstance(parsed, dict):
            return parsed
    except Exception:
        pass

    # 2) 围栏里的 JSON（```json ... ```）
    fence_match = re.search(r"```(?:json)?\s*([\s\S]*?)```", trimmed)
    if fence_match:
        try:
            parsed = json.loads(fence_match.group(1).strip())
            if isinstance(parsed, dict):
                return parsed
        except Exception:
            pass

    # 3) 从第一个 { 到最后一个 }
    start = trimmed.find("{")
    end = trimmed.rfind("}")
    if start != -1 and end > start:
        try:
            parsed = json.loads(trimmed[start : end + 1])
            if isinstance(parsed, dict):
                return parsed
        except Exception:
            pass

    raise ValueError("extractJsonObject: 无法从文本中抽取 JSON 对象")


def now_iso() -> str:
    """对齐 TS 的 new Date().toISOString()。"""
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
