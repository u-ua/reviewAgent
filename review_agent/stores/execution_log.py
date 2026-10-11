"""ExecutionLog：append-only 流水账（对应 src/stores/execution-log.ts）。

事实源就是磁盘上的 execution.jsonl（本实现不另存 SQLite）。只往后追加，不可改历史。
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from threading import RLock

from ..jsonutil import to_json_line
from ..types import ExecutionEvent

CURRENT_EVENT_VERSION = 2


class ExecutionLog:
    def __init__(self, file_path: str):
        self.file_path = Path(file_path)
        self.file_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = RLock()
        self._events: list[ExecutionEvent] = (
            self._read_existing() if self.file_path.exists() else []
        )
        self._started_at = time.monotonic()

    def _read_existing(self) -> list[ExecutionEvent]:
        events: list[ExecutionEvent] = []
        for line in self.file_path.read_text(encoding="utf-8").split("\n"):
            if not line.strip():
                continue
            try:
                events.append(ExecutionEvent.from_dict(json.loads(line)))
            except Exception:
                # 跳过损坏行，账本仍可读
                continue
        return events

    def append(self, evt: dict) -> ExecutionEvent:
        with self._lock:
            seq = len(self._events) + 1
        # v2 引入 tool_access_decision；读取端仍兼容旧的 v1 事件。
            evt.setdefault("eventVersion", CURRENT_EVENT_VERSION)
            evt.setdefault("elapsedMs", round((time.monotonic() - self._started_at) * 1000))
            event = ExecutionEvent(id=f"event:{seq}", seq=seq, **evt)
            self._events.append(event)
            with open(self.file_path, "a", encoding="utf-8") as f:
                f.write(to_json_line(event.to_dict()) + "\n")
            return event

    def list(self) -> list[ExecutionEvent]:
        with self._lock:
            return list(self._events)

    def count(self) -> int:
        with self._lock:
            return len(self._events)
