"""OpenAICompatibleProvider：可选的真实大模型 Provider（对应 src/providers/openai-provider.ts）。

走 OpenAI 兼容 chat.completions + tools 函数调用（标准库 urllib，无第三方依赖），
需要 .env 配置 LLM_API_KEY / LLM_API_BASE_URL / LLM_DEFAULT_MODEL。
未配置时构造即抛错，CLI 会提示改用 --provider fake。
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request

from ..jsonutil import extract_json_object
from ..types import Tool


def load_openai_config_from_env(env: dict | None = None) -> dict:
    """从环境变量读 OpenAI 兼容配置；缺失即抛错。"""
    env = os.environ if env is None else env
    api_key = env.get("LLM_API_KEY") or ""
    base_url = (env.get("LLM_API_BASE_URL") or "").rstrip("/")
    model = env.get("LLM_DEFAULT_MODEL") or ""
    if not api_key or not base_url or not model:
        raise ValueError(
            "缺少 LLM 配置（LLM_API_KEY / LLM_API_BASE_URL / LLM_DEFAULT_MODEL）。"
            "请复制 .env.example 为 .env 填写，或改用 --provider fake 离线运行。"
        )
    return {"apiKey": api_key, "baseUrl": base_url, "model": model}


def to_chat_messages(messages: list) -> list[dict]:
    out: list[dict] = []
    for msg in messages:
        if msg.role == "system":
            out.append({"role": "system", "content": msg.content})
        elif msg.role == "user":
            out.append({"role": "user", "content": msg.content})
        elif msg.role == "assistant":
            if msg.toolName:
                out.append(
                    {
                        "role": "assistant",
                        "content": None,
                        "tool_calls": [
                            {
                                "id": msg.toolCallId or f"call-{len(out)}",
                                "type": "function",
                                "function": {
                                    "name": msg.toolName,
                                    "arguments": json.dumps(msg.toolArgs or {}, ensure_ascii=False),
                                },
                            }
                        ],
                    }
                )
            else:
                out.append({"role": "assistant", "content": msg.content})
        elif msg.role == "tool":
            out.append({"role": "tool", "content": msg.content, "tool_call_id": msg.toolCallId})
    return out


def to_chat_tools(tools: list[Tool]) -> list[dict]:
    return [
        {
            "type": "function",
            "function": {
                "name": tool.name,
                "description": tool.description,
                "parameters": {
                    "type": "object",
                    "properties": {
                        p.name: (
                            {
                                "type": "array",
                                "description": p.description,
                                "items": {"type": p.itemType or "string"},
                            }
                            if p.type == "array"
                            else {"type": p.type, "description": p.description}
                        )
                        for p in tool.parameters
                    },
                    "required": [p.name for p in tool.parameters if p.required],
                    "additionalProperties": False,
                },
            },
        }
        for tool in tools
    ]


class OpenAiProviderSession:
    def __init__(self, cfg: dict, role: str):
        self.cfg = cfg
        self.role = role

    def step(self, messages, tools) -> dict:
        try:
            payload = self._call(messages, tools)
        except Exception as err:
            return {"type": "error", "message": str(err)}

        try:
            choice = (payload.get("choices") or [{}])[0]
            message = choice.get("message") or {}
        except Exception:
            return {"type": "error", "message": f"模型无有效输出: {json.dumps(payload)[:300]}"}
        if not message:
            return {"type": "error", "message": f"模型无有效输出: {json.dumps(payload)[:300]}"}

        tool_calls = message.get("tool_calls")
        usage = payload.get("usage")
        normalized_usage = None
        if isinstance(usage, dict):
            normalized_usage = {
                "promptTokens": usage.get("prompt_tokens"),
                "completionTokens": usage.get("completion_tokens"),
                "totalTokens": usage.get("total_tokens"),
            }
        metadata = {"usage": normalized_usage, "model": payload.get("model") or self.cfg.get("model")}
        if tool_calls:
            first = tool_calls[0]
            raw_args = first.get("function", {}).get("arguments") or "{}"
            try:
                args = json.loads(raw_args)
            except Exception:
                args = extract_json_object(raw_args)
            if not isinstance(args, dict):
                args = {}
            return {"type": "tool_call", "toolName": first.get("function", {}).get("name"), "args": args, **metadata}

        text = message.get("content") or ""
        return {"type": "final", "text": text, **metadata}

    def _call(self, messages, tools) -> dict:
        url = f"{self.cfg['baseUrl']}/chat/completions"
        body = {
            "model": self.cfg["model"],
            "messages": to_chat_messages(messages),
            "tools": to_chat_tools(tools),
            "tool_choice": "auto",
        }
        req = urllib.request.Request(
            url,
            data=json.dumps(body, ensure_ascii=False).encode("utf-8"),
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self.cfg['apiKey']}",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=180) as resp:
                raw = resp.read().decode("utf-8")
        except urllib.error.HTTPError as err:
            text = err.read().decode("utf-8", "replace")[:500]
            raise RuntimeError(f"chat.completions {err.code}: {text}") from err
        except urllib.error.URLError as err:
            raise RuntimeError(f"chat.completions 网络错误: {err.reason}") from err
        return json.loads(raw)


class OpenAiAgentProvider:
    name = "openai"

    def __init__(self, cfg: dict):
        self.cfg = cfg

    def start(self, opts: dict):
        return OpenAiProviderSession(self.cfg, opts.get("role"))
