"""从命令行验证规则语义检索。"""

from __future__ import annotations

import argparse

from qdrant_client import QdrantClient

from review_agent.rag.config import load_rag_config
from review_agent.rag.embeddings import DashScopeEmbeddingClient
from review_agent.rag.store import QdrantRuleStore


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("query")
    parser.add_argument("--language", default="python")
    parser.add_argument("--category")
    parser.add_argument("--limit", type=int, default=5)
    args = parser.parse_args()
    cfg = load_rag_config()
    embedder = DashScopeEmbeddingClient(
        api_key=cfg.api_key,
        base_url=cfg.base_url,
        model=cfg.model,
        dimensions=cfg.dimensions,
    )
    store = QdrantRuleStore(QdrantClient(url=cfg.qdrant_url), cfg.collection, embedder)
    results = store.search(
        args.query,
        language=args.language,
        category=args.category,
        knowledge_version=cfg.knowledge_version,
        limit=args.limit,
    )
    for item in results:
        print(f"{item.score:.4f} {item.rule_id} {item.title} sha256:{item.content_sha256[:12]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
