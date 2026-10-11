"""不变量 5：交卷 ≠ 学籍 —— 员工交 completed 不自动改任务状态（对应 task-status.test.ts，2 条）。"""

from __future__ import annotations

import json
from pathlib import Path

from conftest import demo_repo_root, make_session_dir
from review_agent.controller import ReviewController
from review_agent.providers.fake import FakeAgentProvider

REPO = demo_repo_root()
CASES = json.loads(
    (Path(__file__).resolve().parent.parent / "fixtures" / "cases.json").read_text(encoding="utf-8")
)


def make_config(max_cycles: int) -> dict:
    return {
        "repoRoot": REPO,
        "scope": ["src"],
        "goal": "审查演示仓库的代码质量与安全问题",
        "maxCycles": max_cycles,
        "provider": "fake",
    }


def test_不变量5_并行员工交卷后任务保持running_经理盖章才completed():
    controller = ReviewController(make_config(6), FakeAgentProvider(), session_dir=make_session_dir())

    # 第 1 轮：建两个无依赖任务并并行派发；交卷不自动完成任务。
    r1 = controller.run_once()
    assert r1 == "continue"
    assert controller.taskStore.get_status("task:security") == "running", "交卷后任务应保持 running"
    assert controller.taskStore.get_status("task:logic") == "running", "同批无依赖任务应被领取"
    assert any(
        o.taskId == "task:security" and o.result.status == "completed" for o in controller.outcomes
    ), "员工的 completed 交卷应该被记录"
    assert any(
        o.taskId == "task:logic" and o.result.status == "completed" for o in controller.outcomes
    ), "两个无依赖 Executor 都应在同一批交卷"

    # 第 2 轮：经理看到 completed 交卷后 set_task_status 盖章
    r2 = controller.run_once()
    assert r2 == "continue"
    assert controller.taskStore.get_status("task:security") == "completed", "经理盖章后任务才 completed"


def test_不变量5补_全部任务盖章后总目标收工():
    controller = ReviewController(
        make_config(6), FakeAgentProvider(), session_dir=make_session_dir(), cases=CASES
    )
    result = controller.run_until_done()
    assert result.metrics["hits"] == 8
    assert result.metrics["falsePositives"] == 0
    assert result.metrics["noEvidence"] == 0
    assert controller.goalState["status"] == "completed"
