"""RAG 配置：显式读取环境变量，不把密钥写入日志或异常。"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


def load_env_file(path: str | Path = ".env", env: dict | None = None) -> None:
    """加载简单 KEY=VALUE 文件；已有环境变量优先，不覆盖。"""
    target = os.environ if env is None else env
    file_path = Path(path)
    if not file_path.is_file():
        return
    for raw_line in file_path.read_text(encoding="utf-8-sig").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in target:
            target[key] = value


@dataclass(frozen=True)
class RagConfig:
    provider: str
    api_key: str
    base_url: str
    model: str
    dimensions: int
    qdrant_url: str
    collection: str
    knowledge_version: str = "v1"


def load_rag_config(env: dict | None = None, *, load_dotenv: bool = True) -> RagConfig:
    if env is None:
        if load_dotenv:
            load_env_file()
        env = os.environ

    provider = (env.get("EMBEDDING_PROVIDER") or "dashscope").strip().lower()
    if provider != "dashscope":
        raise ValueError(f"暂不支持 EMBEDDING_PROVIDER={provider}")

    api_key = (env.get("DASHSCOPE_API_KEY") or "").strip()
    if not api_key:
        raise ValueError("缺少 DASHSCOPE_API_KEY")

    try:
        dimensions = int(env.get("EMBEDDING_DIMENSIONS") or "1024")
    except ValueError as err:
        raise ValueError("EMBEDDING_DIMENSIONS 必须是整数") from err
    if dimensions < 64 or dimensions > 2048:
        raise ValueError("EMBEDDING_DIMENSIONS 必须在 64 到 2048 之间")

    return RagConfig(
        provider=provider,
        api_key=api_key,
        base_url=(
            env.get("DASHSCOPE_BASE_URL")
            or "https://dashscope.aliyuncs.com/compatible-mode/v1"
        ).rstrip("/"),
        model=(env.get("EMBEDDING_MODEL") or "text-embedding-v4").strip(),
        dimensions=dimensions,
        qdrant_url=(env.get("QDRANT_URL") or "http://localhost:6333").rstrip("/"),
        collection=(env.get("QDRANT_COLLECTION") or "review_rules_v1").strip(),
        knowledge_version=(env.get("KNOWLEDGE_VERSION") or "v1").strip(),
    )
