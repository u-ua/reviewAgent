"""FindingStore：审查结论档案（findings.json，对应 src/stores/findings-store.ts）。

内存在途，report 阶段统一落盘。
"""

from __future__ import annotations

import json
from pathlib import Path
from threading import RLock

from ..jsonutil import to_json_line
from ..types import Finding


class FindingStore:
    def __init__(self, file_path: str):
        self.file_path = Path(file_path)
        self.file_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = RLock()
        if self.file_path.exists():
            try:
                raw = json.loads(self.file_path.read_text(encoding="utf-8"))
                self._findings = [Finding.from_dict(d) for d in raw]
            except Exception:
                self._findings = []
        else:
            self._findings: list[Finding] = []

    def add(self, finding: Finding) -> None:
        with self._lock:
            self._findings.append(finding)

    def list(self) -> list[Finding]:
        with self._lock:
            return list(self._findings)

    def persist(self) -> None:
        with self._lock:
            self.file_path.write_text(
                to_json_line([f.to_dict() for f in self._findings]), encoding="utf-8"
            )
