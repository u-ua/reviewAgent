"""Provider 协议（对应 src/providers/types.ts）。

运行时按鸭子类型用：provider.start(opts) 返回会话对象，会话对象有
step(messages, tools) -> ProviderStep。这里只写协议供参考/标注。
"""

from __future__ import annotations

from typing import Any, Protocol

ProviderStep = dict[str, Any]


class ProviderSession(Protocol):
    def step(self, messages: list, tools: list) -> ProviderStep:  # pragma: no cover
        ...


class AgentProvider(Protocol):
    name: str

    def start(self, opts: dict) -> ProviderSession:  # pragma: no cover
        ...
