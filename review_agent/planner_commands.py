"""经理的命令语言与校验（对应 src/planner-commands.ts）。

- 命令不合法 → 整批拒绝，带错误反馈给经理重试
- 空命令是一等公民（计划不用改，员工继续），但硬规矩：
  总目标仍 open 且没有任何可继续的任务时，不允许空命令
"""

from __future__ import annotations

import re

from .jsonutil import now_iso
from .types import TaskRecord

TASK_ID_RE = re.compile(r"^task:.+")
PLANNER_TASK_STATUSES = ("open", "completed", "blocked", "failed")
REVIEW_DIMENSIONS = ("security", "performance", "logic")


class PlannerProtocolError(Exception):
    pass


# ---------------------------------------------------------------------------
# 归一化（语法校验）
# ---------------------------------------------------------------------------


def normalize_planner_decision(raw: object) -> dict:
    """把 planner_submit 的原始参数规约为 PlannerDecision；形状不对直接抛错。"""
    if not isinstance(raw, dict):
        raise PlannerProtocolError("规划决策必须是对象")

    reason = raw.get("reason")
    if not isinstance(reason, str) or len(reason) == 0:
        raise PlannerProtocolError("缺少 reason（为什么这样改计划）")

    raw_commands = raw.get("commands")
    if not isinstance(raw_commands, list):
        raise PlannerProtocolError("commands 必须是数组")
    if len(raw_commands) > 32:
        raise PlannerProtocolError("commands 最多 32 条")

    commands = [_normalize_command(c, i) for i, c in enumerate(raw_commands)]
    return {"reason": reason, "commands": commands}


def _normalize_command(raw: object, index: int) -> dict:
    if not isinstance(raw, dict):
        raise PlannerProtocolError(f"commands[{index}] 必须是对象")
    kind = raw.get("kind")
    if kind == "create_tasks":
        tasks_raw = raw.get("tasks")
        if not isinstance(tasks_raw, list) or len(tasks_raw) == 0:
            raise PlannerProtocolError("create_tasks 必须至少建一个任务")
        tasks = [_normalize_task_spec(t, i) for i, t in enumerate(tasks_raw)]
        return {"kind": kind, "tasks": tasks, "basedOnRefs": _normalize_refs(raw.get("basedOnRefs"))}
    if kind == "set_task_status":
        task_id = raw.get("taskId")
        status = raw.get("status")
        if not isinstance(task_id, str) or not task_id:
            raise PlannerProtocolError("set_task_status 缺少 taskId")
        if status not in PLANNER_TASK_STATUSES:
            raise PlannerProtocolError(
                f"set_task_status 的 status 必须是 {'/'.join(PLANNER_TASK_STATUSES)}（running 仅由 Controller 领取任务时写入）"
            )
        return {"kind": kind, "taskId": task_id, "status": status, "basedOnRefs": _normalize_refs(raw.get("basedOnRefs"))}
    if kind == "set_node_status":
        node_id = raw.get("nodeId")
        status = raw.get("status")
        if node_id != "goal:root":
            raise PlannerProtocolError(f"set_node_status 只允许给 goal:root 盖章，收到 {node_id}")
        if status not in ("completed", "blocked"):
            raise PlannerProtocolError("set_node_status 的 status 必须是 completed|blocked")
        return {"kind": kind, "nodeId": node_id, "status": status, "basedOnRefs": _normalize_refs(raw.get("basedOnRefs"))}
    raise PlannerProtocolError(f"未知命令 kind: {kind}（允许 create_tasks/set_task_status/set_node_status）")


def _normalize_task_spec(raw: object, index: int) -> dict:
    if not isinstance(raw, dict):
        raise PlannerProtocolError(f"tasks[{index}] 必须是对象")
    task_id = raw.get("taskId")
    goal = raw.get("goal")
    dimension = raw.get("dimension")
    if not isinstance(task_id, str) or not TASK_ID_RE.match(task_id):
        raise PlannerProtocolError(f"taskId 必须形如 task:xxx，收到 {task_id}")
    if not isinstance(goal, str) or len(goal) == 0:
        raise PlannerProtocolError(f"任务 {task_id} 缺少 goal")
    if dimension not in REVIEW_DIMENSIONS:
        raise PlannerProtocolError(
            f"任务 {task_id} 的 dimension 必须是 {'|'.join(REVIEW_DIMENSIONS)}"
        )
    return {
        "taskId": task_id,
        "goal": goal,
        "dimension": dimension,
        "successCriteria": _string_array(raw.get("successCriteria"), f"任务 {task_id} successCriteria"),
        "dependsOnTaskRefs": _string_array(raw.get("dependsOnTaskRefs"), f"任务 {task_id} dependsOnTaskRefs"),
    }


def _string_array(value: object, label: str) -> list[str] | None:
    if value is None:
        return None
    if not isinstance(value, list) or any(not isinstance(v, str) for v in value):
        raise PlannerProtocolError(f"{label} 必须是字符串数组")
    return value


def _normalize_refs(value: object) -> list[str] | None:
    if value is None:
        return None
    if not isinstance(value, list) or any(not isinstance(v, str) for v in value):
        raise PlannerProtocolError("basedOnRefs 必须是字符串数组")
    return value


# ---------------------------------------------------------------------------
# 语义校验（整批）
# ---------------------------------------------------------------------------


def validate_planner_commands(decision: dict, task_store: object) -> list[str]:
    """校验命令在任务图上的语义合法性，返回错误列表；空数组 = 合法。"""
    errors: list[str] = []
    creating: set[str] = set()
    for cmd in decision["commands"]:
        kind = cmd["kind"]
        if kind == "create_tasks":
            for spec in cmd["tasks"]:
                task_id = spec["taskId"]
                if task_id in creating:
                    errors.append(f"同一批重复创建任务 {task_id}")
                creating.add(task_id)
                if task_store.get(task_id) is not None:
                    errors.append(f"任务已存在，不能重复创建 {task_id}")
                deps = spec.get("dependsOnTaskRefs") or []
                if task_id in deps:
                    errors.append(f"任务 {task_id} 不能依赖自己")
                for dep in deps:
                    if dep not in creating and task_store.get(dep) is None:
                        errors.append(f"任务 {task_id} 依赖不存在的任务 {dep}")
        elif kind == "set_task_status":
            if task_store.get(cmd["taskId"]) is None:
                errors.append(f"set_task_status 引用不存在的任务 {cmd['taskId']}")
        elif kind == "set_node_status":
            if cmd["nodeId"] != "goal:root":
                errors.append("set_node_status 只能作用于 goal:root")

    # 环检测：新任务的依赖链不能成环
    all_ids = set(creating) | {t.taskId for t in task_store.list()}
    deps_of: dict[str, list[str]] = {t.taskId: list(t.dependsOnTaskRefs) for t in task_store.list()}
    for cmd in decision["commands"]:
        if cmd["kind"] == "create_tasks":
            for spec in cmd["tasks"]:
                deps_of[spec["taskId"]] = list(spec.get("dependsOnTaskRefs") or [])
    for id_ in all_ids:
        if _has_cycle(id_, deps_of, set()):
            errors.append(f"依赖成环，涉及任务 {id_}")

    # 去重保序
    return list(dict.fromkeys(errors))


def _has_cycle(start: str, deps_of: dict[str, list[str]], visiting: set[str]) -> bool:
    if start in visiting:
        return True
    visiting.add(start)
    for dep in deps_of.get(start, []):
        if _has_cycle(dep, deps_of, visiting):
            return True
    visiting.discard(start)
    return False


# ---------------------------------------------------------------------------
# 应用（写任务图）
# ---------------------------------------------------------------------------


def apply_planner_commands(decision: dict, task_store: object, goal_state: dict, now: str | None = None) -> None:
    """把合法命令写进任务图。"""
    now = now or now_iso()
    for cmd in decision["commands"]:
        kind = cmd["kind"]
        if kind == "create_tasks":
            for spec in cmd["tasks"]:
                task_store.add(
                    TaskRecord(
                        taskId=spec["taskId"],
                        goal=spec["goal"],
                        successCriteria=list(spec.get("successCriteria") or []),
                        status="open",
                        dependsOnTaskRefs=list(spec.get("dependsOnTaskRefs") or []),
                        maxTurns=20,
                        createdAt=now,
                        dimension=spec["dimension"],
                    )
                )
        elif kind == "set_task_status":
            task_store.set_status(cmd["taskId"], cmd["status"])
        elif kind == "set_node_status":
            if cmd["nodeId"] == "goal:root":
                goal_state["status"] = cmd["status"]


# ---------------------------------------------------------------------------
# 空命令规矩
# ---------------------------------------------------------------------------


def assert_planner_idle_decision_can_continue(decision: dict, task_store: object, goal_state: dict) -> None:
    """空命令是合法的 quiescent 信号，但总目标 open 且无 ready 任务时不允许。"""
    idle = len(decision["commands"]) == 0
    if idle and goal_state["status"] == "open" and len(task_store.ready_tasks()) == 0:
        raise PlannerProtocolError(
            "总目标仍进行中且没有任何可继续的任务：空命令不被允许。"
            "你必须创建/恢复可推进的任务，或把总目标标记为 completed/blocked。"
        )
