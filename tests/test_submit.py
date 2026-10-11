"""不变量 4：没打卡不算结束（对应 tests/submit.test.ts，2 条）。

员工 maxTurns 用完还没调 task_result_submit → MissingSubmitError，本轮作废。
只在正文说"审完了"不算数。
"""

from __future__ import annotations

import pytest

from conftest import demo_repo_root, make_ctx
from review_agent.agents import create_executor_tools
from review_agent.session import RoleSession
from review_agent.types import MissingSubmitError, TaskRecord


class TalkOnlyProvider:
    """只会口头说"审完了"、从不调用提交工具的假模型。"""

    name = "talk-only"

    def start(self, opts):
        return _TalkOnlySession()


class _TalkOnlySession:
    def step(self, messages, tools):
        return {"type": "final", "text": "我审完了，所有问题都检查过了。"}


def test_不变量4_只说_审完了_没打卡_MissingSubmitError():
    provider = TalkOnlyProvider()
    ctx = make_ctx(repo_root=demo_repo_root(), scope=["src"])
    session = RoleSession(
        role="executor",
        system_prompt="审代码",
        user_input="任务：审 src",
        tools=create_executor_tools(),
        provider=provider,
        max_turns=3,
        ctx=ctx,
    )

    with pytest.raises(MissingSubmitError) as exc:
        session.run()
    assert exc.value.role == "executor"


class ChatThenSubmitProvider:
    """会在正文唠叨两句后打卡的模型。"""

    name = "chat-then-submit"

    def start(self, opts):
        return _ChatThenSubmitSession()


class _ChatThenSubmitSession:
    def __init__(self):
        self._turns = 0

    def step(self, messages, tools):
        self._turns += 1
        if self._turns == 1:
            return {"type": "final", "text": "我先看看代码。"}
        return {
            "type": "tool_call",
            "toolName": "task_result_submit",
            "args": {
                "taskId": "task:x",
                "status": "completed",
                "summary": "审完了",
                "evidenceRefs": [],
                "artifactRefs": [],
            },
        }


def test_不变量4补_调用_terminate_打卡才结束():
    provider = ChatThenSubmitProvider()
    ctx = make_ctx(repo_root=demo_repo_root(), scope=["src"])
    ctx.stores.taskStore.add(
        TaskRecord(
            taskId="task:x",
            goal="审",
            successCriteria=[],
            status="open",
            dependsOnTaskRefs=[],
            maxTurns=20,
            createdAt="2026-01-01T00:00:00.000Z",
        )
    )

    session = RoleSession(
        role="executor",
        system_prompt="审代码",
        user_input="任务：审 src",
        tools=create_executor_tools(),
        provider=provider,
        max_turns=5,
        ctx=ctx,
    )

    result = session.run()
    assert result.terminateTool == "task_result_submit"
    assert result.submitArgs["status"] == "completed"
