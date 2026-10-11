"""将受控规则文件生成向量并幂等写入 Qdrant。"""

from __future__ import annotations

import argparse

from qdrant_client import QdrantClient

from review_agent.rag.config import load_rag_config
from review_agent.rag.embeddings import DashScopeEmbeddingClient
from review_agent.rag.loader import load_rules
from review_agent.rag.store import QdrantRuleStore


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--rules", default="knowledge/review_rules.json")
    args = parser.parse_args()
    cfg = load_rag_config()
    embedder = DashScopeEmbeddingClient(
        api_key=cfg.api_key,
        base_url=cfg.base_url,
        model=cfg.model,
        dimensions=cfg.dimensions,
    )
    store = QdrantRuleStore(QdrantClient(url=cfg.qdrant_url), cfg.collection, embedder)
    store.ensure_collection(create_payload_indexes=True)
    rules = load_rules(args.rules, knowledge_version=cfg.knowledge_version)
    count = store.upsert_rules(rules)
    print(f"已写入 {count} 条规则：{cfg.collection} ({cfg.model}, {cfg.dimensions} 维)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
