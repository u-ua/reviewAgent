"""OWASP Cheat Sheet 分块索引；默认 dry-run，--write 才调用 embedding。"""

from __future__ import annotations

import argparse

from qdrant_client import QdrantClient

from review_agent.rag.config import load_rag_config
from review_agent.rag.embeddings import DashScopeEmbeddingClient
from review_agent.rag.owasp_loader import load_owasp_rules
from review_agent.rag.store import QdrantRuleStore


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--chunks", default="knowledge/normalized/owasp_cheatsheets.jsonl")
    parser.add_argument("--knowledge-version", default="v1")
    parser.add_argument("--batch-size", type=int, default=10)
    parser.add_argument("--write", action="store_true")
    args = parser.parse_args()
    if args.batch_size < 1 or args.batch_size > 100:
        parser.error("--batch-size 必须在 1 到 100 之间")

    rules = load_owasp_rules(args.chunks, knowledge_version=args.knowledge_version)
    print(f"筛选结果: {len({rule.rule_id for rule in rules})} 份 Cheat Sheet, {len(rules)} 个分块")
    if not args.write:
        print("dry-run 完成；添加 --write 后才会调用 embedding 并写入 Qdrant")
        return 0

    cfg = load_rag_config()
    if args.knowledge_version != cfg.knowledge_version:
        raise ValueError("--knowledge-version 必须与 KNOWLEDGE_VERSION 一致")
    embedder = DashScopeEmbeddingClient(
        api_key=cfg.api_key, base_url=cfg.base_url,
        model=cfg.model, dimensions=cfg.dimensions,
    )
    store = QdrantRuleStore(QdrantClient(url=cfg.qdrant_url), cfg.collection, embedder)
    store.ensure_collection(create_payload_indexes=True)
    written = 0
    for start in range(0, len(rules), args.batch_size):
        written += store.upsert_rules(rules[start:start + args.batch_size])
        print(f"写入进度: {written}/{len(rules)}")
    print(f"已写入 {written} 个 OWASP 分块：{cfg.collection}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
