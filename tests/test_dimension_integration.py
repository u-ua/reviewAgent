"""多维度任务协议、派发和兼容性。"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from conftest import demo_repo_root, make_session_dir
from review_agent.controller import ReviewController
from review_agent.planner_commands import PlannerProtocolError, apply_planner_commands, normalize_planner_decision
from review_agent.providers.fake import FakeAgentProvider
from review_agent.stores.task_store import TaskStore
from review_agent.types import TaskRecord


def _create(dimension: str) -> dict:
    return {"reason": "按维度审查", "commands": [{"kind": "create_tasks", "tasks": [{
        "taskId": f"task:{dimension}", "goal": "审查", "dimension": dimension,
    }]}]}


def test_三个维度任务均能正常创建():
    store = TaskStore(str(Path(make_session_dir()) / "tasks.json"))
    commands = []
    for dimension in ("security", "performance", "logic"):
        commands.extend(_create(dimension)["commands"])
    decision = normalize_planner_decision({"reason": "多维度", "commands": commands})
    apply_planner_commands(decision, store, {"status": "open"})
    assert [task.dimension for task in store.list()] == ["security", "performance", "logic"]


def test_未知任务维度被拒绝():
    with pytest.raises(PlannerProtocolError, match="dimension"):
        normalize_planner_decision(_create("style"))


def test_旧tasks_json缺dimension默认security():
    path = Path(make_session_dir()) / "tasks.json"
    path.write_text(json.dumps([{
        "taskId": "task:old", "goal": "旧任务", "successCriteria": [], "status": "open",
        "dependsOnTaskRefs": [], "maxTurns": 20, "createdAt": "2026-01-01T00:00:00Z",
    }]), encoding="utf-8")
    assert TaskStore(str(path)).get("task:old").dimension == "security"


def test_序列化往返保留dimension():
    task = TaskRecord("task:perf", "性能", [], "open", [], 20, "2026-01-01T00:00:00Z", "performance")
    assert TaskRecord.from_dict(task.to_dict()).dimension == "performance"


@pytest.mark.parametrize("dimension, marker", [
    ("security", "当前维度：security"),
    ("performance", "当前维度：performance"),
    ("logic", "当前维度：logic"),
])
def test_Controller按任务维度选择Executor提示词(dimension, marker):
    controller = ReviewController(
        {"repoRoot": demo_repo_root(), "scope": ["src"], "goal": "审查", "maxCycles": 1, "provider": "fake"},
        FakeAgentProvider(), session_dir=make_session_dir(),
    )
    task = TaskRecord(f"task:{dimension}", "审查", [], "open", [], 1, "2026-01-01T00:00:00Z", dimension)
    controller.run_executor_task(task)
    # Provider 收到的任务单亦为同一维度；task_started 事件可审计该维度。
    started = controller.executionLog.list()[0]
    assert started.taskId == task.taskId
    assert started.payload["dimension"] == dimension
    assert marker in __import__("review_agent.prompts", fromlist=["get_executor_system_prompt"]).get_executor_system_prompt(dimension)
