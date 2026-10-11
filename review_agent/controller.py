"""ReviewController：调度中枢（对应 src/controller.ts，同步实现）。

一轮 runOnce 的顺序：
  1. 请经理规划（planner_submit）→ 校验命令 → 整批打回重试
  2. 命令写进任务图；若给 goal:root 盖章则收工
  3. assert_planner_idle_decision_can_continue：总目标仍 open 且无活可干时空命令非法
  4. 原子领取一批无依赖 ready 任务，有限并发派给员工；员工打卡 task_result_submit
  5. 交卷 ≠ 学籍：员工 completed 不自动改任务状态，要经理 set_task_status 盖章
"""

from __future__ import annotations

import os
import random
import string
import re as _re
from concurrent.futures import ThreadPoolExecutor
from threading import Lock
from pathlib import Path

from .agents import create_executor_tools, create_planner_tools
from .jsonutil import now_iso
from .planner_commands import (
    PlannerProtocolError,
    apply_planner_commands,
    assert_planner_idle_decision_can_continue,
    normalize_planner_decision,
    validate_planner_commands,
)
from .prompts import (
    PLANNER_SYSTEM_PROMPT,
    get_executor_system_prompt,
    render_executor_input,
    render_planner_input,
)
from .report import write_report
from .metrics import write_metrics
from .session import RoleSession
from .stores.artifact_store import ArtifactStore
from .stores.execution_log import ExecutionLog
from .stores.finding_store import FindingStore
from .stores.task_store import TaskStore
from .types import (
    ReviewRunConfig,
    RunResult,
    TaskOutcome,
    TaskRecord,
    TaskResult,
    ToolContext,
    Stores,
)

PLANNER_REPAIR_ATTEMPTS = 2
PLANNER_MAX_TURNS = 3

RESULT_STATUSES = ("completed", "partial", "blocked", "failed")


def _default_session_dir() -> str:
    ts = _re.sub(r"[:.]", "-", now_iso())
    rand = "".join(random.choices(string.ascii_lowercase + string.digits, k=6))
    return str(Path("runs") / f"{ts}-{rand}")


def _coerce_config(config) -> ReviewRunConfig:
    if isinstance(config, ReviewRunConfig):
        return config
    d = config
    return ReviewRunConfig(
        repoRoot=d["repoRoot"],
        goal=d["goal"],
        maxCycles=d["maxCycles"],
        provider=d["provider"],
        scope=list(d.get("scope") or []),
        base=d.get("base"),
        maxTurnsPerTask=d.get("maxTurnsPerTask"),
        modelPricing=dict(d.get("modelPricing") or {}),
        maxConcurrentExecutors=max(1, int(d.get("maxConcurrentExecutors", 2))),
    )


def normalize_task_result(args: dict, fallback_task_id: str) -> TaskResult:
    """员工交卷参数 → TaskResult（只信任形状，越界的 status 落 failed）。"""
    status = args.get("status")
    return TaskResult(
        taskId=args.get("taskId") if isinstance(args.get("taskId"), str) and args.get("taskId") else fallback_task_id,
        status=status if status in RESULT_STATUSES else "failed",
        summary=args.get("summary") if isinstance(args.get("summary"), str) else "（无摘要）",
        evidenceRefs=args.get("evidenceRefs") if isinstance(args.get("evidenceRefs"), list) else [],
        artifactRefs=args.get("artifactRefs") if isinstance(args.get("artifactRefs"), list) else [],
        blockerReason=args.get("blockerReason") if isinstance(args.get("blockerReason"), str) else None,
        suggestedNextGoal=args.get("suggestedNextGoal") if isinstance(args.get("suggestedNextGoal"), str) else None,
    )


class ReviewController:
    def __init__(self, config, provider, *, session_dir: str | None = None, cases=None, rag_store=None):
        self.config = _coerce_config(config)
        self.provider = provider
        self.cases = cases
        self.rag_store = rag_store
        self.session_dir = session_dir or _default_session_dir()
        Path(self.session_dir).mkdir(parents=True, exist_ok=True)
        self.executionLog = ExecutionLog(str(Path(self.session_dir) / "execution.jsonl"))
        self.artifactStore = ArtifactStore(
            artifacts_dir=str(Path(self.session_dir) / "artifacts"),
            run_id=os.path.basename(self.session_dir),
        )
        self.taskStore = TaskStore(str(Path(self.session_dir) / "tasks.json"))
        self.findingStore = FindingStore(str(Path(self.session_dir) / "findings.json"))
        self.goalState = {"status": "open"}
        self.outcomes: list[TaskOutcome] = []
        self.epoch_counter = 0
        self._outcomes_lock = Lock()
        self._epoch_lock = Lock()

    # ------------------------------------------------------------------
    # 公开
    # ------------------------------------------------------------------

    def run_once(self) -> str:
        """一轮，返回 'continue' | 'done' | 'failed'。"""
        planner_tools = create_planner_tools()
        planner_ctx = self.make_ctx()

        decision = self.invoke_planner_with_repair(planner_tools, planner_ctx)
        if decision is None:
            self.log_event("runtime", "planner_failed", "规划连续被驳回，本轮作废")
            return "failed"

        apply_planner_commands(decision, self.taskStore, self.goalState)
        self.log_event(
            "planner",
            "decision_applied",
            f"经理决策：{decision['reason']}",
            {"commandCount": len(decision["commands"]), "commands": [c["kind"] for c in decision["commands"]]},
        )

        if self.goalState["status"] != "open":
            self.log_event("runtime", "goal_completed", f"总目标已{self.goalState['status']}")
            return "done"

        try:
            assert_planner_idle_decision_can_continue(decision, self.taskStore, self.goalState)
        except PlannerProtocolError as err:
            self.log_event("runtime", "planner_idle_rejected", str(err))
            return "failed"

        # Planner 仍串行；同一批无依赖任务在 TaskStore 内原子领取并标为
        # running，避免被两个 Executor 重复派发。批次结束后才回到 Planner。
        ready = self.taskStore.claim_ready_tasks(self.config.maxConcurrentExecutors)
        if ready:
            with ThreadPoolExecutor(max_workers=len(ready), thread_name_prefix="review-executor") as pool:
                list(pool.map(self.run_executor_task, ready))
        return "continue"

    def run_until_done(self) -> RunResult:
        """整场运行直到总目标完成或循环上限，写报告。"""
        self.log_event("runtime", "run_started", f"审查目标：{self.config.goal}", {"scope": self.config.scope})
        cycles = 0
        finish = "continue"
        while self.goalState["status"] == "open" and cycles < self.config.maxCycles:
            cycles += 1
            finish = self.run_once()
            if finish != "continue":
                break
        if self.goalState["status"] == "open":
            self.log_event("runtime", "run_max_cycles", f"达到最大循环数 {self.config.maxCycles}，目标未完成")
            finish = "failed"

        self.findingStore.persist()
        report_path, metrics = write_report(
            session_dir=self.session_dir,
            config=self.config,
            findings=self.findingStore.list(),
            tasks=self.taskStore.list(),
            outcomes=self.outcomes,
            cases=self.cases,
            artifact_store=self.artifactStore,
        )
        self.log_event("runtime", "run_finished", f"运行结束（{finish}），报告：{os.path.basename(report_path)}")
        metrics_projection = write_metrics(self.session_dir, self.config.modelPricing)
        # 保持 RunResult 既有评测字段（hits 等）兼容，同时暴露账本投影。
        run_metrics = {**metrics, "runtime": metrics_projection}

        return RunResult(
            sessionDir=self.session_dir,
            config=self.config,
            findings=self.findingStore.list(),
            tasks=self.taskStore.list(),
            outcomes=self.outcomes,
            metrics=run_metrics,
            reportPath=report_path,
        )

    # ------------------------------------------------------------------
    # 私有
    # ------------------------------------------------------------------

    def invoke_planner_with_repair(self, planner_tools, planner_ctx):
        """请经理规划；决策被整批驳回就打回重试（最多 PLANNER_REPAIR_ATTEMPTS 次）。"""
        repair_error: str | None = None

        for _attempt in range(PLANNER_REPAIR_ATTEMPTS + 1):
            base_input = render_planner_input(
                goal=self.config.goal,
                scope=self.config.scope,
                tasks=self.taskStore.list(),
                outcomes=self.outcomes,
            )
            if repair_error:
                user_input = f"{base_input}\n\n[系统] 你上一次的决策被驳回：{repair_error}\n请重新规划。"
            else:
                user_input = base_input

            session = RoleSession(
                role="planner",
                system_prompt=PLANNER_SYSTEM_PROMPT,
                user_input=user_input,
                tools=planner_tools,
                provider=self.provider,
                max_turns=PLANNER_MAX_TURNS,
                ctx=planner_ctx,
                hint={
                    "role": "planner",
                    "goal": self.config.goal,
                    "scope": self.config.scope,
                    "tasks": self.taskStore.list(),
                    "outcomes": self.outcomes,
                },
            )

            try:
                result = session.run()
                submit_args = result.submitArgs
            except Exception as err:
                repair_error = str(err)
                continue

            try:
                decision = normalize_planner_decision(submit_args)
                errors = validate_planner_commands(decision, self.taskStore)
                if len(errors) > 0:
                    repair_error = "; ".join(errors)
                    continue
                return decision
            except Exception as err:
                repair_error = str(err)
                continue
        return None

    def run_executor_task(self, task: TaskRecord) -> None:
        with self._epoch_lock:
            self.epoch_counter += 1
            epoch_id = f"epoch-{self.epoch_counter}"
        envelope = {
            "taskId": task.taskId,
            "goal": task.goal,
            "dimension": task.dimension,
            "successCriteria": task.successCriteria,
            "scopeRef": self.config.scope,
            "dependsOnTaskRefs": task.dependsOnTaskRefs,
            "budget": {"maxTurns": task.maxTurns},
        }
        ctx = self.make_ctx(task.taskId, epoch_id, task.dimension)
        self.executionLog.append(
            {
                "role": "runtime",
                "eventType": "task_started",
                "taskId": task.taskId,
                "epochId": epoch_id,
                "summary": f"派发任务 {task.taskId}（{epoch_id}）",
                "artifactRefs": [],
                "payload": {"dimension": task.dimension},
            }
        )

        session = RoleSession(
            role="executor",
            system_prompt=get_executor_system_prompt(task.dimension),
            user_input=render_executor_input(envelope),
            tools=create_executor_tools(include_rag=self.rag_store is not None),
            provider=self.provider,
            max_turns=envelope["budget"]["maxTurns"],
            ctx=ctx,
            hint={"role": "executor", "task": envelope},
        )

        try:
            result = session.run()
            task_result = normalize_task_result(result.submitArgs, task.taskId)
            with self._outcomes_lock:
                self.outcomes.append(
                    TaskOutcome(taskId=task.taskId, epochId=epoch_id, result=task_result, createdAt=now_iso())
                )
            # 注意：交卷不自动改任务状态 —— 员工 completed ≠ 学籍完成，等经理盖章。
        except Exception as err:
            self.log_event("runtime", "task_failed", f"任务 {task.taskId} 执行失败：{err}")
            with self._outcomes_lock:
                self.outcomes.append(
                    TaskOutcome(
                        taskId=task.taskId,
                        epochId=epoch_id,
                        result=TaskResult(
                            taskId=task.taskId,
                            status="failed",
                            summary=f"执行失败：{err}",
                            evidenceRefs=[],
                            artifactRefs=[],
                        ),
                        createdAt=now_iso(),
                    )
                )
        finally:
            self.executionLog.append({"role": "runtime", "eventType": "task_finished", "taskId": task.taskId,
                "epochId": epoch_id, "summary": f"任务结束 {task.taskId}", "artifactRefs": [],
                "payload": {"dimension": task.dimension}})

    def make_ctx(self, task_id: str | None = None, epoch_id: str | None = None, task_dimension: str = "security") -> ToolContext:
        return ToolContext(
            runId=os.path.basename(self.session_dir),
            taskId=task_id,
            epochId=epoch_id,
            taskDimension=task_dimension,
            repoRoot=self.config.repoRoot,
            scope=self.config.scope,
            stores=Stores(
                executionLog=self.executionLog,
                artifactStore=self.artifactStore,
                findingStore=self.findingStore,
                taskStore=self.taskStore,
                ragStore=self.rag_store,
            ),
        )

    def log_event(self, role: str, event_type: str, summary: str, payload=None) -> None:
        self.executionLog.append(
            {"role": role, "eventType": event_type, "summary": summary, "artifactRefs": [], "payload": payload}
        )
