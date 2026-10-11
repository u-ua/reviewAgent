"""FakeAgentProvider：默认的确定性假 LLM，无需网络、无需 API key（对应 fake-provider.ts）。

- 假经理：根据任务图状态提交 planner_submit（建任务 / 盖章 / 空命令）
- 假员工：grep 定位缺陷行 → read_file 取证 → finding_write（引用真实证据）→ task_result_submit

8 条规则逐条对应 fake-provider.ts（含大小写、惰性量词），命中即产出 Finding，
评测数字（命中 8 / 误报 0 / 无证据 0）可复现。
"""

from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass
class ReviewRule:
    id: str
    severity: str
    title: str
    rationale: str
    suggestion: str
    source: str
    ignorecase: bool

    @property
    def regex(self) -> re.Pattern:
        if not hasattr(self, "_regex"):
            flags = re.IGNORECASE if self.ignorecase else 0
            self._regex = re.compile(self.source, flags)
        return self._regex


SECURITY_RULES: list[ReviewRule] = [
    ReviewRule(
        id="sql-concat",
        severity="high",
        title="SQL 字符串拼接存在注入风险",
        rationale="用字符串拼接把变量放进 SQL 语句，用户可控值可改变语句结构，造成 SQL 注入。",
        suggestion="改用参数化查询 / PreparedStatement，变量作为参数传入，而不是拼进 SQL 文本。",
        source=r"SELECT[\s\S]{0,120}?(?:['\"`]\s*\+|\$\{|\.format)",
        ignorecase=True,
    ),
    ReviewRule(
        id="hardcoded-secret",
        severity="critical",
        title="硬编码敏感信息",
        rationale="密码/密钥直接写在源码里，会随代码泄露，且无法单独轮换。",
        suggestion="移到环境变量或密钥管理系统，代码中只引用名称。",
        source=r"(?:password|passwd|api[_-]?key|secret|token|credential)\s*[:=]\s*['\"][A-Za-z0-9_\-+/=*]{6,}['\"]",
        ignorecase=True,
    ),
    ReviewRule(
        id="eval-usage",
        severity="critical",
        title="使用 eval 执行动态代码",
        rationale="eval 把字符串当代码执行，输入不可信时可导致任意代码执行。",
        suggestion="避免 eval，改用 JSON.parse 等安全解析方式。",
        source=r"\beval\s*\(",
        ignorecase=True,
    ),
    ReviewRule(
        id="reflected-input",
        severity="medium",
        title="用户输入直接回显到响应（反射）",
        rationale="未校验的用户输入直接拼进响应，可能造成反射型 XSS 或响应混淆。",
        suggestion="对输出做 HTML 转义，或使用框架的自动转义模板。",
        source=r"res\.(?:send|end|write|json)\([^)]*(?:req\.|req\[|\.query|\.params|\.body)",
        ignorecase=True,
    ),
    ReviewRule(
        id="open-redirect",
        severity="medium",
        title="开放重定向",
        rationale="根据用户输入把请求重定向到外部地址，可用于钓鱼攻击。",
        suggestion="只允许重定向到站内白名单地址。",
        source=r"(?:res\.redirect|location\.href)\s*\([^)]*(?:req\.|url|returnUrl|next|redirect)",
        ignorecase=True,
    ),
    ReviewRule(
        id="innerhtml-xss",
        severity="high",
        title="innerHTML 写入未净化内容",
        rationale="直接把字符串写进 innerHTML，内容含 HTML/脚本时会被执行，造成 XSS。",
        suggestion="使用 textContent，或先经过 DOMPurify 等净化再写入。",
        source=r"\.innerHTML\s*=",
        ignorecase=True,
    ),
]

QUALITY_RULES: list[ReviewRule] = [
    ReviewRule(
        id="error-leak",
        severity="medium",
        title="异常信息泄漏到日志",
        rationale="把异常对象直接打进日志或响应，可能暴露内部调用栈、路径、库版本等敏感信息。",
        suggestion="记录异常 ID 与安全摘要，完整堆栈写入受限的日志存储。",
        source=r"(?:console\.(?:error|log)\([^)]*err|new Error\(`[^`]*\$\{\w*err)",
        ignorecase=True,
    ),
    ReviewRule(
        id="empty-catch",
        severity="medium",
        title="空 catch 吞掉错误",
        rationale="catch 块为空，故障被静默吞掉，后续逻辑可能在错误状态下继续。",
        suggestion="至少记录日志，或把异常重新抛出 / 回退到安全默认值。",
        source=r"catch\s*\([^)]*\)\s*\{\s*\}",
        ignorecase=False,
    ),
]

ALL_RULES = [*SECURITY_RULES, *QUALITY_RULES]

def combined_pattern(rules: list[ReviewRule]) -> str:
    return "|".join(r.source for r in rules)


def rules_for_dimension(dimension: str) -> list[ReviewRule]:
    """假 Provider 也遵守任务维度，不靠目标文本猜测。"""
    if dimension == "security":
        return SECURITY_RULES
    if dimension == "logic":
        return QUALITY_RULES
    return []


# ---------------------------------------------------------------------------
# 解析工具结果
# ---------------------------------------------------------------------------

_GREP_LINE_RE = re.compile(r"^(.+?):(\d+): (.*)$")
_ARTIFACT_REF_RE = re.compile(r"^artifactRef: (.+)$", re.MULTILINE)


def parse_grep_matches(text: str) -> list[dict]:
    matches: list[dict] = []
    for line in text.split("\n"):
        m = _GREP_LINE_RE.match(line)
        if m:
            matches.append({"path": m.group(1), "line": int(m.group(2)), "content": m.group(3)})
    return matches


def last_tool_content(messages: list) -> str:
    for msg in reversed(messages):
        if getattr(msg, "role", None) == "tool":
            return getattr(msg, "content", "") or ""
    return ""


def extract_artifact_ref(content: str) -> str | None:
    m = _ARTIFACT_REF_RE.search(content)
    return m.group(1) if m else None


# ---------------------------------------------------------------------------
# 假经理
# ---------------------------------------------------------------------------


class FakePlannerSession:
    def __init__(self, hint: dict):
        self.hint = hint

    def step(self, messages, tools) -> dict:
        commands = self._build_commands()
        if len(commands) == 0:
            reason = "计划不变，员工继续"
        else:
            reason = f"本轮规划：{', '.join(c['kind'] for c in commands)}"
        return {"type": "tool_call", "toolName": "planner_submit", "args": {"reason": reason, "commands": commands}}

    def _build_commands(self) -> list[dict]:
        tasks = self.hint["tasks"]
        outcomes = self.hint["outcomes"]
        if len(tasks) == 0:
            return [
                {
                    "kind": "create_tasks",
                    "tasks": [
                        {
                            "taskId": "task:security",
                            "dimension": "security",
                            "goal": "审查范围内的安全缺陷（信息泄漏、SQL 注入、XSS、硬编码密钥等）",
                            "successCriteria": ["找出安全问题并给出建议", "每条 Finding 带行号和证据"],
                        },
                        {
                            "taskId": "task:logic",
                            "dimension": "logic",
                            "goal": "审查错误处理与输入校验等代码质量问题",
                            "successCriteria": ["找出错误处理与校验缺陷", "每条 Finding 带行号和证据"],
                        },
                    ],
                }
            ]

        commands: list[dict] = []
        submitted_completed = {o.taskId for o in outcomes if o.result.status == "completed"}

        for task in tasks:
            if task.status == "running" and task.taskId in submitted_completed:
                commands.append({"kind": "set_task_status", "taskId": task.taskId, "status": "completed"})

        all_completed = len(tasks) > 0 and all(t.status == "completed" for t in tasks)
        any_failed = any(t.status in ("failed", "blocked") for t in tasks)
        if all_completed:
            commands.append({"kind": "set_node_status", "nodeId": "goal:root", "status": "completed"})
        elif any_failed and all(t.status != "open" for t in tasks):
            commands.append({"kind": "set_node_status", "nodeId": "goal:root", "status": "blocked"})
        return commands


# ---------------------------------------------------------------------------
# 假员工
# ---------------------------------------------------------------------------


class FakeExecutorSession:
    def __init__(self, hint: dict, *, include_rag: bool = False):
        self.task_id = hint["task"]["taskId"]
        self.dimension = hint["task"].get("dimension", "security")
        self.include_rag = include_rag
        self.rules = rules_for_dimension(self.dimension)
        self.phase: str = "grep"
        self.findings_by_file: dict[str, list[dict]] = {}
        self.file_order: list[str] = []
        self.refs_by_file: dict[str, str] = {}
        self.rule_evidence_refs: list[str] = []
        self.finding_counter = 0

    def step(self, messages, tools) -> dict:
        if self.phase == "grep":
            self.phase = "analyze"
            return {"type": "tool_call", "toolName": "grep", "args": {"pattern": combined_pattern(self.rules)}}
        if self.phase == "analyze":
            content = last_tool_content(messages)
            for m in parse_grep_matches(content):
                rule = next((r for r in self.rules if r.regex.search(m["content"])), None)
                if rule is None:
                    continue
                self.findings_by_file.setdefault(m["path"], []).append({"line": m["line"], "rule": rule})
            self.file_order = list(self.findings_by_file.keys())
            if len(self.file_order) == 0:
                self.phase = "submit"
                return self.submit_step()
            self.phase = "read"
            return {"type": "tool_call", "toolName": "read_file", "args": {"path": self.file_order[0]}}
        if self.phase == "read":
            ref = extract_artifact_ref(last_tool_content(messages))
            current_file = self.file_order[0]
            if ref:
                self.refs_by_file[current_file] = ref
            if self.dimension == "security" and self.include_rag:
                self.phase = "rule"
                return {
                    "type": "tool_call",
                    "toolName": "search_review_rules",
                    "args": {"query": "security code review", "language": "typescript", "category": "security"},
                }
            self.phase = "write"
            return self.next_finding_step(current_file)
        if self.phase == "rule":
            ref = extract_artifact_ref(last_tool_content(messages))
            if ref:
                self.rule_evidence_refs = [ref]
            self.phase = "write"
            return self.next_finding_step(self.file_order[0])
        if self.phase == "write":
            return self.next_finding_step(self.file_order[0])
        return self.submit_step()

    def next_finding_step(self, current_file: str) -> dict:
        """写当前文件的下一条 Finding；写完了切下一个文件，没有文件了就打卡。"""
        findings = self.findings_by_file.get(current_file, [])
        next_f = next((f for f in findings if not f.get("written")), None)
        if next_f is not None:
            next_f["written"] = True
            ref = self.refs_by_file.get(current_file)
            self.finding_counter += 1
            return {
                "type": "tool_call",
                "toolName": "finding_write",
                "args": {
                    "id": f"finding-{self.finding_counter}",
                    "severity": next_f["rule"].severity,
                    "path": current_file,
                    "startLine": next_f["line"],
                    "endLine": next_f["line"],
                    "title": next_f["rule"].title,
                    "rationale": next_f["rule"].rationale,
                    "suggestion": next_f["rule"].suggestion,
                    "evidenceRefs": [ref] if ref else [],
                    "dimension": self.dimension,
                    "ruleEvidenceRefs": self.rule_evidence_refs,
                },
            }
        # 当前文件写完，换下一个
        self.file_order.pop(0)
        if len(self.file_order) == 0:
            self.phase = "submit"
            return self.submit_step()
        self.phase = "read"
        return {"type": "tool_call", "toolName": "read_file", "args": {"path": self.file_order[0]}}

    def submit_step(self) -> dict:
        evidence_refs = list(self.refs_by_file.values())
        matched_paths = list(self.findings_by_file.keys())
        return {
            "type": "tool_call",
            "toolName": "task_result_submit",
            "args": {
                "taskId": self.task_id,
                "status": "completed",
                "summary": f"已审查 {len(matched_paths)} 个文件，报告 {self.finding_counter} 条 Finding",
                "evidenceRefs": evidence_refs,
                "artifactRefs": evidence_refs,
            },
        }


# ---------------------------------------------------------------------------
# Provider
# ---------------------------------------------------------------------------


class FakeAgentProvider:
    name = "fake"

    def start(self, opts: dict):
        if opts.get("role") == "planner":
            hint = opts.get("hint") or {}
            return FakePlannerSession(
                {
                    "role": "planner",
                    "goal": hint.get("goal") or "",
                    "scope": hint.get("scope") or [],
                    "tasks": hint.get("tasks") or [],
                    "outcomes": hint.get("outcomes") or [],
                }
            )
        hint = opts.get("hint") or {}
        if "task" not in hint:
            raise ValueError("fake provider 的 executor 需要 hint.task（TaskEnvelope）")
        return FakeExecutorSession(
            {"role": "executor", "task": hint["task"]},
            include_rag=any(getattr(tool, "name", None) == "search_review_rules" for tool in opts.get("tools", [])),
        )
