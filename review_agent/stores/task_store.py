"""TaskStore：任务图（对应 src/stores/task-store.ts）。

用 tasks.json 的 JSON 列表 + 依赖，不上 SQLite 三图。
交卷 ≠ 学籍：员工交 completed 不会自动改这里的 status，只有经理
set_task_status 才改。ready_tasks() 只放依赖全部 completed 的 open 任务。
"""

from __future__ import annotations

import json
from pathlib import Path
from threading import RLock

from ..jsonutil import to_json_line
from ..types import TaskRecord


class TaskStore:
    def __init__(self, file_path: str):
        self.file_path = Path(file_path)
        self.file_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = RLock()
        if self.file_path.exists():
            try:
                raw = json.loads(self.file_path.read_text(encoding="utf-8"))
                self._tasks = [TaskRecord.from_dict(d) for d in raw]
            except Exception:
                self._tasks = []
        else:
            self._tasks: list[TaskRecord] = []

    def _persist(self) -> None:
        self.file_path.write_text(
            to_json_line([t.to_dict() for t in self._tasks]), encoding="utf-8"
        )

    def list(self) -> list[TaskRecord]:
        with self._lock:
            return list(self._tasks)

    def get(self, task_id: str) -> TaskRecord | None:
        with self._lock:
            return next((t for t in self._tasks if t.taskId == task_id), None)

    def add(self, task: TaskRecord) -> None:
        with self._lock:
            if self.get(task.taskId) is not None:
                raise ValueError(f"任务已存在: {task.taskId}")
            self._tasks.append(task)
            self._persist()

    def set_status(self, task_id: str, status: str) -> None:
        with self._lock:
            task = self.get(task_id)
            if task is None:
                raise ValueError(f"任务不存在: {task_id}")
            task.status = status
            self._persist()

    def list_open_tasks(self) -> list[TaskRecord]:
        with self._lock:
            return [t for t in self._tasks if t.status == "open"]

    def ready_tasks(self) -> list[TaskRecord]:
        """依赖全部 completed 的 open 任务 —— 可以派活。"""
        with self._lock:
            return [
                t
                for t in self._tasks
                if t.status == "open"
                and all(
                    (self.get(dep) is not None and self.get(dep).status == "completed")
                    for dep in t.dependsOnTaskRefs
                )
            ]

    def claim_ready_tasks(self, max_tasks: int) -> list[TaskRecord]:
        """原子领取一批 ready 任务；running 仅由 Controller 写入。"""
        if max_tasks < 1:
            raise ValueError("max_tasks 必须至少为 1")
        with self._lock:
            claimed = self.ready_tasks()[:max_tasks]
            for task in claimed:
                task.status = "running"
            if claimed:
                self._persist()
            return list(claimed)

    def get_status(self, task_id: str) -> str | None:
        with self._lock:
            task = self.get(task_id)
            return task.status if task else None
