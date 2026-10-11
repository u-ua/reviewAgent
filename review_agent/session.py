"""RoleSession：结构化打卡循环（对应 src/session.ts）。

- 轮流问 Provider，执行工具，把结果喂回去
- 模型只在正文说"审完了"不算数；必须调用 terminate 工具（打卡）
- maxTurns 用尽还没打卡 → MissingSubmitError，本轮作废
- 工具报错不回崩整个 Run，而是把错误喂回模型重试

本迁移用同步实现（fake/openai 均无并发需求），协议顺序与 TS 完全一致。
"""

from __future__ import annotations

import time

from .types import (
    AgentSessionResult,
    MissingSubmitError,
    SessionMessage,
    Tool,
    ToolCallRecord,
    ToolContext,
)

RESULT_FEEDBACK_MAX = 4000


def validate_tool_args(tool: Tool, args: dict) -> str | None:
    """基本参数类型校验，返回错误信息或 None。"""
    for param in tool.parameters:
        value = args.get(param.name)
        if value is None:
            if param.required:
                return f"缺少参数 {param.name}"
            continue
        if param.type == "string":
            if not isinstance(value, str):
                return f"参数 {param.name} 必须是字符串"
        elif param.type == "number":
            if not isinstance(value, (int, float)) or isinstance(value, bool):
                return f"参数 {param.name} 必须是数字"
        elif param.type == "boolean":
            if not isinstance(value, bool):
                return f"参数 {param.name} 必须是布尔值"
        elif param.type == "array":
            if not isinstance(value, list):
                return f"参数 {param.name} 必须是数组"
            if param.itemType == "string" and any(not isinstance(v, str) for v in value):
                return f"参数 {param.name} 必须是字符串数组"
    return None


def _tool_result_text(result: dict) -> str:
    if not result.get("ok"):
        return f"工具执行失败: {result.get('error') or result.get('summary')}"
    body = result.get("text") or result.get("summary")
    if len(body) > RESULT_FEEDBACK_MAX:
        return body[:RESULT_FEEDBACK_MAX] + "\n...(结果过长已截断)"
    return body


def _sanitize_args(args: dict) -> dict:
    """只保留小参数进账本，避免大文本污染事件行。"""
    out: dict = {}
    for k, v in args.items():
        if isinstance(v, str) and len(v) > 200:
            out[k] = f"({len(v)} 字符，省略)"
        else:
            out[k] = v
    return out


class RoleSession:
    def __init__(
        self,
        *,
        role: str,
        system_prompt: str,
        user_input: str,
        tools: list[Tool],
        provider: object,
        max_turns: int,
        ctx: ToolContext,
        hint: dict | None = None,
    ):
        self.role = role
        self.system_prompt = system_prompt
        self.user_input = user_input
        self.tools = tools
        self.provider = provider
        self.max_turns = max_turns
        self.ctx = ctx
        self.hint = hint

    def run(self) -> AgentSessionResult:
        messages: list[SessionMessage] = [
            SessionMessage(role="system", content=self.system_prompt),
            SessionMessage(role="user", content=self.user_input),
        ]
        tool_calls: list[ToolCallRecord] = []
        provider_session = self.provider.start(
            {
                "role": self.role,
                "systemPrompt": self.system_prompt,
                "userInput": self.user_input,
                "hint": self.hint,
                "tools": self.tools,
            }
        )

        terminate_names = " / ".join(t.name for t in self.tools if t.terminate)

        for turn in range(1, self.max_turns + 1):
            # 问 Provider 要下一步
            llm_started = time.monotonic()
            try:
                step = provider_session.step(messages, self.tools)
            except Exception as err:
                self._log_llm_call(round((time.monotonic() - llm_started) * 1000), False, None)
                messages.append(SessionMessage(role="user", content=f"模型调用失败: {err}。请重新作答。"))
                continue
            self._log_llm_call(round((time.monotonic() - llm_started) * 1000), step.get("type") != "error", step)

            if step.get("type") == "error":
                messages.append(
                    SessionMessage(role="user", content=f"输出无法解析: {step.get('message')}。请重新作答。")
                )
                continue
            if step.get("type") == "final":
                # 口头宣布完成不算数
                messages.append(
                    SessionMessage(
                        role="user",
                        content=f"本轮你还没有打卡。必须调用 {terminate_names} 提交才算结束。",
                    )
                )
                continue

            tool = next((t for t in self.tools if t.name == step.get("toolName")), None)
            if tool is None:
                available = ", ".join(t.name for t in self.tools)
                self.ctx.stores.executionLog.append({
                    "role": self.role, "eventType": "tool_access_decision", "taskId": self.ctx.taskId,
                    "epochId": self.ctx.epochId, "summary": "未授权工具调用决策", "artifactRefs": [],
                    "payload": {"reason": "role_tool_denied", "tool": str(step.get("toolName") or ""), "allowed": False, "blocked": True},
                })
                messages.append(
                    SessionMessage(role="user", content=f"工具不存在: {step.get('toolName')}。可用工具: {available}")
                )
                continue

            args = step.get("args") or {}
            invalid = validate_tool_args(tool, args)
            if invalid:
                messages.append(SessionMessage(role="user", content=f"参数非法: {invalid}"))
                continue

            # 先记录 assistant 的工具调用，再执行（保证 API 消息序列配对）
            messages.append(
                SessionMessage(
                    role="assistant",
                    content="",
                    toolName=tool.name,
                    toolCallId=f"call-{turn}",
                    toolArgs=args,
                )
            )

            # 执行工具；异常不回崩，喂回重试
            tool_started = time.monotonic()
            try:
                result = tool.execute(args, self.ctx)
            except Exception as err:
                result = {"ok": False, "summary": f"工具执行异常: {err}", "error": str(err)}

            call = ToolCallRecord(id=f"call-{turn}", name=tool.name, args=args, result=result)
            tool_calls.append(call)

            self._log(tool, args, result, round((time.monotonic() - tool_started) * 1000))

            if tool.terminate:
                if not result.get("ok"):
                    messages.append(
                        SessionMessage(
                            role="user",
                            content=f"打卡工具执行失败: {result.get('error')}。请修正后重新打卡。",
                        )
                    )
                    continue
                return AgentSessionResult(terminateTool=tool.name, submitArgs=args, toolCalls=tool_calls)

            evidence_line = f"artifactRef: {result['artifactRef']}\n" if result.get("artifactRef") else ""
            messages.append(
                SessionMessage(
                    role="tool",
                    toolName=tool.name,
                    toolCallId=call.id,
                    content=f"工具 {tool.name} 结果:\n{evidence_line}{_tool_result_text(result)}",
                )
            )

        raise MissingSubmitError(self.role, self.max_turns)

    def _log_llm_call(self, duration_ms: int, success: bool, step: dict | None) -> None:
        usage = step.get("usage") if isinstance(step, dict) else None
        synthetic = bool(step.get("synthetic")) if isinstance(step, dict) else False
        if getattr(self.provider, "name", None) == "fake" and usage is None:
            usage, synthetic = {"promptTokens": 0, "completionTokens": 0, "totalTokens": 0}, True
        payload = {
            "durationMs": duration_ms,
            "success": success,
            "model": step.get("model") if isinstance(step, dict) else None,
            "usage": usage if isinstance(usage, dict) else None,
            "synthetic": synthetic,
        }
        self.ctx.stores.executionLog.append({"role": self.role, "eventType": "llm_call", "taskId": self.ctx.taskId,
            "epochId": self.ctx.epochId, "summary": "LLM 调用", "artifactRefs": [], "payload": payload})

    def _log(self, tool: Tool, args: dict, result: dict, duration_ms: int) -> None:
        event_type = "submit" if tool.terminate else "tool_call"
        if tool.name == "finding_write":
            event_type = "finding_accepted" if result.get("ok") else "finding_rejected"
        safe_args = args if tool.terminate else _sanitize_args(args)
        if tool.name == "finding_write":
            safe_args = {k: args.get(k) for k in ("id", "severity", "path", "startLine", "endLine", "dimension")}
        evt = {
            "role": self.role,
            "eventType": event_type,
            "taskId": self.ctx.taskId,
            "epochId": self.ctx.epochId,
            "summary": result.get("summary", ""),
            "payload": {"tool": tool.name, "args": safe_args, "dimension": self.ctx.taskDimension,
                        "durationMs": duration_ms, "ok": bool(result.get("ok")),
                        "rejectionReason": result.get("rejectionReason")},
            "artifactRefs": [result["artifactRef"]] if result.get("artifactRef") else [],
        }
        self.ctx.stores.executionLog.append(evt)

        if not result.get("ok") and tool.name in ("read_file", "finding_write"):
            error = str(result.get("error") or "")
            reason = self._scope_reason(error)
            if reason:
                self.ctx.stores.executionLog.append({"role": self.role, "eventType": "tool_access_decision",
                    "taskId": self.ctx.taskId, "epochId": self.ctx.epochId, "summary": "越权工具调用决策",
                    "artifactRefs": [], "payload": {"reason": reason, "tool": tool.name, "allowed": False, "blocked": True}})

    @staticmethod
    def _scope_reason(error: str) -> str | None:
        lowered = error.lower()
        if "路径穿越" in error or "../" in error: return "path_traversal"
        if "超出审查范围" in error: return "outside_scope"
        if "敏感文件" in error or ".git" in error: return "sensitive_path"
        if "符号链接逃逸" in error: return "symlink_escape"
        if "绝对路径" in error: return "absolute_path"
        return None
