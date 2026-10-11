"""Embedding Provider；生产使用百炼，测试可注入确定性假实现。"""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from typing import Protocol, Sequence


class EmbeddingClient(Protocol):
    model: str
    dimensions: int

    def embed(self, texts: Sequence[str]) -> list[list[float]]: ...


class DashScopeEmbeddingClient:
    def __init__(self, *, api_key: str, base_url: str, model: str, dimensions: int):
        self._api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.dimensions = dimensions

    def embed(self, texts: Sequence[str]) -> list[list[float]]:
        inputs = list(texts)
        if not inputs or any(not isinstance(text, str) or not text.strip() for text in inputs):
            raise ValueError("Embedding 输入必须是非空字符串列表")
        body = {
            "model": self.model,
            "input": inputs,
            "dimensions": self.dimensions,
            "encoding_format": "float",
        }
        request = urllib.request.Request(
            f"{self.base_url}/embeddings",
            data=json.dumps(body, ensure_ascii=False).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {self._api_key}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=60) as response:
                payload = json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as err:
            detail = err.read().decode("utf-8", "replace")[:500]
            raise RuntimeError(f"Embedding API {err.code}: {detail}") from err
        except urllib.error.URLError as err:
            raise RuntimeError(f"Embedding API 网络错误: {err.reason}") from err

        rows = sorted(payload.get("data") or [], key=lambda item: item.get("index", 0))
        vectors = [row.get("embedding") for row in rows]
        if len(vectors) != len(inputs) or any(not isinstance(vector, list) for vector in vectors):
            raise RuntimeError("Embedding API 返回数量或格式异常")
        if any(len(vector) != self.dimensions for vector in vectors):
            raise RuntimeError("Embedding API 返回维度与配置不一致")
        return vectors
