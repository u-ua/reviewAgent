"""筛选 CWE 分块；默认 dry-run，只有显式 --write 才调用 embedding 并写入 Qdrant。"""

from __future__ import annotations

import argparse
from collections import Counter

from qdrant_client import QdrantClient

from review_agent.rag.config import load_rag_config
from review_agent.rag.cwe_loader import load_cwe_rules
from review_agent.rag.embeddings import DashScopeEmbeddingClient
from review_agent.rag.store import QdrantRuleStore


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--chunks", default="knowledge/normalized/cwe.jsonl")
    parser.add_argument("--scope", default="knowledge/cwe_review_scope.json")
    parser.add_argument("--knowledge-version", default="v1")
    parser.add_argument("--batch-size", type=int, default=10)
    parser.add_argument("--write", action="store_true", help="真实调用 embedding 并写入 Qdrant")
    args = parser.parse_args()
    if args.batch_size < 1 or args.batch_size > 100:
        parser.error("--batch-size 必须在 1 到 100 之间")

    rules = load_cwe_rules(
        args.chunks,
        args.scope,
        knowledge_version=args.knowledge_version,
    )
    by_section = Counter(rule.section_type for rule in rules)
    cwe_count = len({rule.rule_id for rule in rules})
    print(f"筛选结果: {cwe_count} 个 CWE, {len(rules)} 个分块")
    print("章节分布: " + ", ".join(f"{key}={value}" for key, value in sorted(by_section.items())))
    if not args.write:
        print("dry-run 完成；添加 --write 后才会调用 embedding 并写入 Qdrant")
        return 0

    cfg = load_rag_config()
    if args.knowledge_version != cfg.knowledge_version:
        raise ValueError("--knowledge-version 必须与 KNOWLEDGE_VERSION 一致，确保检索过滤可命中")
    embedder = DashScopeEmbeddingClient(
        api_key=cfg.api_key,
        base_url=cfg.base_url,
        model=cfg.model,
        dimensions=cfg.dimensions,
    )
    store = QdrantRuleStore(QdrantClient(url=cfg.qdrant_url), cfg.collection, embedder)
    store.ensure_collection(create_payload_indexes=True)
    written = 0
    for start in range(0, len(rules), args.batch_size):
        written += store.upsert_rules(rules[start:start + args.batch_size])
        print(f"写入进度: {written}/{len(rules)}")
    print(f"已写入 {written} 个 CWE 分块：{cfg.collection}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
