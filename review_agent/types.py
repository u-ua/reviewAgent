"""领域模型（对应 src/types.ts，单据逐一对齐）。

单据用 dataclass / Literal 写死；不上 Pydantic、不上 LangChain。
工具 execute 保持「参数 dict + ctx → ToolResult(dict)」形状，与 TS 一致。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Literal, NotRequired, TypedDict

TaskStatus = Literal["open", "running", "completed", "blocked", "failed", "archived"]
TaskResultStatus = Literal["completed", "partial", "blocked", "failed"]
Severity = Literal["critical", "high", "medium", "low"]
ArtifactKind = Literal["code", "diff", "listing", "report", "rule", "other"]
AgentRole = Literal["planner", "executor", "runtime"]
ReviewDimension = Literal["security", "performance", "logic"]


@dataclass
class ReviewCase:
    """评测标准答案（L0 案例）。"""

    path: str
    startLine: int
    type: str
    severity: str
    why: str
    suggestion: str

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "ReviewCase":
        keys = set(cls.__dataclass_fields__)
        return cls(**{k: v for k, v in d.items() if k in keys})


@dataclass
class ReviewMetrics:
    """评测三数字。"""

    hits: int
    falsePositives: int
    noEvidence: int
    totalCases: int

    def to_dict(self) -> dict[str, int]:
        return {
            "hits": self.hits,
            "falsePositives": self.falsePositives,
            "noEvidence": self.noEvidence,
            "totalCases": self.totalCases,
        }


@dataclass
class TaskRecord:
    """任务图里的一条任务（持久化在 tasks.json）。"""

    taskId: str
    goal: str
    successCriteria: list[str]
    status: TaskStatus
    dependsOnTaskRefs: list[str]
    maxTurns: int
    createdAt: str
    # 旧 tasks.json 没有该字段时按安全审查处理，保证可直接恢复历史运行。
    dimension: ReviewDimension = "security"

    def to_dict(self) -> dict[str, Any]:
        return {
            "taskId": self.taskId,
            "goal": self.goal,
            "successCriteria": self.successCriteria,
            "status": self.status,
            "dependsOnTaskRefs": self.dependsOnTaskRefs,
            "maxTurns": self.maxTurns,
            "createdAt": self.createdAt,
            "dimension": self.dimension,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "TaskRecord":
        keys = set(cls.__dataclass_fields__)
        values = {k: v for k, v in d.items() if k in keys}
        values.setdefault("dimension", "security")
        return cls(**values)


@dataclass
class TaskResult:
    """员工的交卷单。员工交什么不等同学籍怎么改。"""

    taskId: str
    status: TaskResultStatus
    summary: str
    evidenceRefs: list[str]
    artifactRefs: list[str]
    blockerReason: str | None = None
    suggestedNextGoal: str | None = None

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {
            "taskId": self.taskId,
            "status": self.status,
            "summary": self.summary,
            "evidenceRefs": self.evidenceRefs,
            "artifactRefs": self.artifactRefs,
        }
        if self.blockerReason is not None:
            d["blockerReason"] = self.blockerReason
        if self.suggestedNextGoal is not None:
            d["suggestedNextGoal"] = self.suggestedNextGoal
        return d

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "TaskResult":
        keys = set(cls.__dataclass_fields__)
        return cls(**{k: v for k, v in d.items() if k in keys})


@dataclass
class TaskOutcome:
    """一次交卷在账本里的存档。"""

    taskId: str
    epochId: str
    result: TaskResult
    createdAt: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "taskId": self.taskId,
            "epochId": self.epochId,
            "result": self.result.to_dict(),
            "createdAt": self.createdAt,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "TaskOutcome":
        return cls(
            taskId=d["taskId"],
            epochId=d["epochId"],
            result=TaskResult.from_dict(d["result"]),
            createdAt=d["createdAt"],
        )


@dataclass
class Finding:
    """一条代码审查结论；RAG 模式额外要求规则证据。"""

    id: str
    severity: Severity
    path: str
    startLine: int
    endLine: int
    title: str
    rationale: str
    suggestion: str
    evidenceRefs: list[str]
    taskId: str | None = None
    ruleEvidenceRefs: list[str] = field(default_factory=list)
    dimension: ReviewDimension = "security"

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {
            "id": self.id,
            "severity": self.severity,
            "path": self.path,
            "startLine": self.startLine,
            "endLine": self.endLine,
            "title": self.title,
            "rationale": self.rationale,
            "suggestion": self.suggestion,
            "evidenceRefs": self.evidenceRefs,
        }
        if self.taskId is not None:
            d["taskId"] = self.taskId
        if self.ruleEvidenceRefs:
            d["ruleEvidenceRefs"] = self.ruleEvidenceRefs
        d["dimension"] = self.dimension
        return d

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "Finding":
        keys = set(cls.__dataclass_fields__)
        values = {k: v for k, v in d.items() if k in keys}
        values.setdefault("dimension", "security")
        return cls(**values)


@dataclass
class ArtifactRecord:
    """内容寻址证据袋里的一条记录。"""

    artifactRef: str
    taskId: str
    kind: ArtifactKind
    mediaType: str
    path: str
    byteLength: int
    createdAt: str
    preview: str
    contentHash: str
    # 代码片段的原始位置。规则、diff 等没有时为 None；Finding 用它核对行号。
    sourcePath: str | None = None
    sourceStartLine: int | None = None
    sourceEndLine: int | None = None


@dataclass
class ExecutionEvent:
    """流水账里的一行（execution.jsonl）。"""

    id: str
    seq: int
    role: AgentRole
    eventType: str
    summary: str
    artifactRefs: list[str]
    taskId: str | None = None
    epochId: str | None = None
    payload: Any = None
    # 事件 schema 的版本；旧账本没有该字段时按 v1 读取。
    eventVersion: int = 1
    # 相对本次运行开始的单调时钟毫秒数。旧账本可为空。
    elapsedMs: int | None = None

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {
            "id": self.id,
            "seq": self.seq,
            "role": self.role,
            "eventType": self.eventType,
            "summary": self.summary,
            "artifactRefs": self.artifactRefs,
        }
        if self.taskId is not None:
            d["taskId"] = self.taskId
        if self.epochId is not None:
            d["epochId"] = self.epochId
        if self.payload is not None:
            d["payload"] = self.payload
        d["eventVersion"] = self.eventVersion
        if self.elapsedMs is not None:
            d["elapsedMs"] = self.elapsedMs
        return d

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "ExecutionEvent":
        keys = set(cls.__dataclass_fields__)
        values = {k: v for k, v in d.items() if k in keys}
        values.setdefault("eventVersion", 1)
        return cls(**values)


@dataclass
class ToolParam:
    """一个工具参数。"""

    name: str
    type: str
    description: str
    required: bool
    itemType: str | None = None


ToolResult = dict[str, Any]


@dataclass
class Tool:
    """一个工具：参数 Schema + 执行函数。terminate=True 表示打卡即本轮结束。"""

    name: str
    description: str
    parameters: list[ToolParam]
    execute: Callable[[dict[str, Any], "ToolContext"], ToolResult]
    terminate: bool = False


@dataclass
class Stores:
    """工具执行上下文里的存储集。"""

    executionLog: Any
    artifactStore: Any
    findingStore: Any
    taskStore: Any
    ragStore: Any = None


@dataclass
class ToolContext:
    """工具执行上下文：只读仓库能力 + 账本能力。"""

    runId: str
    repoRoot: str
    scope: list[str]
    stores: Stores
    taskId: str | None = None
    epochId: str | None = None
    taskDimension: ReviewDimension = "security"


class MissingSubmitError(Exception):
    """用尽轮次仍未打卡，本轮作废（对应 src/types.ts 的 MissingSubmitError）。"""

    def __init__(self, role: str, max_turns: int):
        self.role = role
        self.max_turns = max_turns
        super().__init__(f"{role} 在 {max_turns} 轮内没有调用 terminate 提交工具，本轮作废")


# ---------------------------------------------------------------------------
# Planner 命令语言
# ---------------------------------------------------------------------------


class TaskSpec(TypedDict):
    taskId: str
    goal: str
    dimension: ReviewDimension
    successCriteria: NotRequired[list[str]]
    dependsOnTaskRefs: NotRequired[list[str]]


class CreateTasksCommand(TypedDict):
    kind: Literal["create_tasks"]
    tasks: list[TaskSpec]
    basedOnRefs: NotRequired[list[str]]


class SetTaskStatusCommand(TypedDict):
    kind: Literal["set_task_status"]
    taskId: str
    status: Literal["open", "completed", "blocked", "failed"]
    basedOnRefs: NotRequired[list[str]]


class SetNodeStatusCommand(TypedDict):
    kind: Literal["set_node_status"]
    nodeId: str
    status: Literal["completed", "blocked"]
    basedOnRefs: NotRequired[list[str]]


PlannerCommand = CreateTasksCommand | SetTaskStatusCommand | SetNodeStatusCommand


class TaskEnvelope(TypedDict):
    """Controller 交给 Executor 的只读任务单。"""

    taskId: str
    goal: str
    dimension: ReviewDimension
    successCriteria: list[str]
    scopeRef: list[str]
    dependsOnTaskRefs: list[str]
    budget: dict[str, int]


class PlannerDecision(TypedDict):
    reason: str
    commands: list[PlannerCommand]


class GoalState(TypedDict):
    """总目标盖章状态（可变，manager 在 controller 持有）。"""

    status: Literal["open", "completed", "blocked"]


# ---------------------------------------------------------------------------
# 会话 / Provider 单据
# ---------------------------------------------------------------------------


@dataclass
class SessionMessage:
    role: str
    content: str
    toolCallId: str | None = None
    toolName: str | None = None
    toolArgs: dict[str, Any] | None = None


@dataclass
class ToolCallRecord:
    """会话中一次工具调用的记录（供 provider 回显）。"""

    id: str
    name: str
    args: dict[str, Any]
    result: dict[str, Any]


@dataclass
class AgentSessionResult:
    """一次结构化 Agent 会话的产出：模型决定调用哪个 terminate 工具（打卡）。"""

    terminateTool: str
    submitArgs: dict[str, Any]
    toolCalls: list[ToolCallRecord]


# 一次 provider 决定：tool_call / final / error（运行时用 dict，形状与 TS ProviderStep 一致）
ProviderStep = dict[str, Any]


# ---------------------------------------------------------------------------
# 运行配置 / 结果
# ---------------------------------------------------------------------------


@dataclass
class ReviewRunConfig:
    """代码审查运行的配置输入。"""

    repoRoot: str
    goal: str
    maxCycles: int
    provider: str
    scope: list[str] = field(default_factory=list)
    base: str | None = None
    maxTurnsPerTask: int | None = None
    # 同一批无依赖任务的 Executor 上限；Planner 始终串行。
    maxConcurrentExecutors: int = 2
    # model -> {inputPer1K, outputPer1K}; 只放价格，绝不放 API Key。
    modelPricing: dict[str, dict[str, float]] = field(default_factory=dict)


@dataclass
class RunResult:
    """一次运行的产物摘要。"""

    sessionDir: str
    config: ReviewRunConfig
    findings: list[Finding]
    tasks: list[TaskRecord]
    outcomes: list[TaskOutcome]
    metrics: dict[str, Any]
    reportPath: str
