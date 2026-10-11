"""不变量 1 与 6：经理工具箱隔离 + 空命令规矩（对应 tests/planner.test.ts，3 条）。"""

from __future__ import annotations

from pathlib import Path

import pytest

from conftest import make_session_dir
from review_agent.agents import create_planner_tools
from review_agent.planner_commands import (
    PlannerProtocolError,
    assert_planner_idle_decision_can_continue,
)
from review_agent.stores.task_store import TaskStore
from review_agent.types import TaskRecord


def test_不变量1_Planner_工具箱不含任何只读源码工具():
    tools = create_planner_tools()
    names = [t.name for t in tools]
    assert names == ["planner_submit"]
    for forbidden in ["read_file", "grep", "list_files", "git_diff", "finding_write"]:
        assert forbidden not in names, f"Planner 不应有 {forbidden}"


def test_不变量6_goal仍open且无任务时空命令非法():
    task_store = TaskStore(str(Path(make_session_dir()) / "tasks.json"))
    goal_state = {"status": "open"}
    empty = {"reason": "计划不变", "commands": []}
    with pytest.raises(PlannerProtocolError):
        assert_planner_idle_decision_can_continue(empty, task_store, goal_state)


def test_不变量6补_有可继续任务时空命令合法():
    session_dir = make_session_dir()
    task_store = TaskStore(str(Path(session_dir) / "tasks.json"))
    task_store.add(
        TaskRecord(
            taskId="task:a",
            goal="审一个任务",
            successCriteria=[],
            status="open",
            dependsOnTaskRefs=[],
            maxTurns=20,
            createdAt="2026-01-01T00:00:00.000Z",
        )
    )
    goal_state = {"status": "open"}
    empty = {"reason": "计划不变，员工继续", "commands": []}
    # 不该抛
    assert_planner_idle_decision_can_continue(empty, task_store, goal_state)


def test_任务领取_只领取无依赖任务并标记running():
    session_dir = make_session_dir()
    task_store = TaskStore(str(Path(session_dir) / "tasks.json"))
    task_store.add(TaskRecord("task:a", "独立任务", [], "open", [], 20, "2026-01-01T00:00:00.000Z"))
    task_store.add(TaskRecord("task:b", "独立任务", [], "open", [], 20, "2026-01-01T00:00:00.000Z"))
    task_store.add(TaskRecord("task:c", "依赖任务", [], "open", ["task:a"], 20, "2026-01-01T00:00:00.000Z"))

    claimed = task_store.claim_ready_tasks(2)

    assert [task.taskId for task in claimed] == ["task:a", "task:b"]
    assert task_store.get_status("task:a") == "running"
    assert task_store.get_status("task:b") == "running"
    assert task_store.get_status("task:c") == "open"
