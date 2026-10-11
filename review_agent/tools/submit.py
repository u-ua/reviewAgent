"""打卡工具：planner_submit（经理）/ task_result_submit（员工）。

对应 src/tools/submit-tools.ts。都带 terminate=True —— 一打卡，本轮结束。
模型只在正文说"审完了"不算数。
"""

from __future__ import annotations

import json

from ..types import Tool, ToolParam

RESULT_STATUSES = ("completed", "partial", "blocked", "failed")


def _fail(message: str) -> dict:
    return {"ok": False, "summary": f"提交被拒绝: {message}", "error": message}


def _task_result_submit_execute(args, ctx) -> dict:
    task_id = args.get("taskId")
    status = args.get("status")
    summary = args.get("summary")
    evidence_refs = args.get("evidenceRefs") or []
    artifact_refs = args.get("artifactRefs") or []

    if not isinstance(task_id, str) or ctx.stores.taskStore.get(task_id) is None:
        return _fail(f"任务不存在: {task_id}")
    if status not in RESULT_STATUSES:
        return _fail(f"status 必须是 {'/'.join(RESULT_STATUSES)}")
    if not isinstance(summary, str) or len(summary) == 0:
        return _fail("summary 不能为空")
    if not isinstance(evidence_refs, list) or not isinstance(artifact_refs, list):
        return _fail("evidenceRefs/artifactRefs 必须是数组")
    for ref in list(evidence_refs) + list(artifact_refs):
        if not isinstance(ref, str):
            return _fail("引用必须是字符串")
        if not ctx.stores.artifactStore.has(ref):
            return _fail(f"引用不存在: {ref}")

    return {
        "ok": True,
        "summary": f"任务 {task_id} 交卷 {status}: {summary}",
        "text": json.dumps({"taskId": task_id, "status": status, "summary": summary}, ensure_ascii=False),
    }


def _planner_submit_execute(args, ctx) -> dict:
    reason = args.get("reason")
    commands = args.get("commands")
    if not isinstance(reason, str) or len(reason) == 0:
        return _fail("reason 不能为空")
    if not isinstance(commands, list):
        return _fail("commands 必须是数组")
    if len(commands) > 32:
        return _fail("commands 最多 32 条")
    # 命令的深层语义校验由 Controller 统一处理，这里是快速形状检查
    return {"ok": True, "summary": f"经理提交规划决策: {reason}"}


def build_task_result_submit_tool() -> Tool:
    return Tool(
        name="task_result_submit",
        description=(
            "员工打卡交卷：汇报本任务结果。status 四种：completed/partial/blocked/failed。"
            "交卷不自动改任务状态，需经理盖章。"
        ),
        terminate=True,
        parameters=[
            ToolParam("taskId", "string", "任务单号", True),
            ToolParam("status", "string", "completed|partial|blocked|failed", True),
            ToolParam("summary", "string", "已确认什么、还差什么", True),
            ToolParam("evidenceRefs", "array", "支撑结论的事件/证据引用", True, itemType="string"),
            ToolParam("artifactRefs", "array", "大证据文件编号", True, itemType="string"),
            ToolParam("blockerReason", "string", "blocked 时卡在哪", False),
            ToolParam("suggestedNextGoal", "string", "建议经理下一步看什么", False),
        ],
        execute=_task_result_submit_execute,
    )


def build_planner_submit_tool() -> Tool:
    return Tool(
        name="planner_submit",
        description=(
            "经理打卡：提交规划决策。commands 是改任务图的命令"
            "（create_tasks/set_task_status/set_node_status），可为空（表示计划不变，员工继续）。"
            "不能口头宣布完成。"
        ),
        terminate=True,
        parameters=[
            ToolParam("reason", "string", "为什么这样改计划", True),
            ToolParam("commands", "array", "改图命令列表（对象数组，可空）", True),
        ],
        execute=_planner_submit_execute,
    )
