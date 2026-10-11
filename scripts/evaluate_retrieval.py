"""在真实 Qdrant + embedding 上运行规则级检索评测。"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from qdrant_client import QdrantClient

from review_agent.rag.config import load_rag_config
from review_agent.rag.embeddings import DashScopeEmbeddingClient
from review_agent.rag.evaluation import (
    RetrievalCaseResult,
    compute_retrieval_metrics,
    unique_rule_ranking,
)
from review_agent.rag.store import QdrantRuleStore


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--cases", default="knowledge/retrieval_eval_cases.json")
    parser.add_argument("--candidate-limit", type=int, default=50)
    parser.add_argument("--mode", choices=("dense", "hybrid"), default="dense")
    parser.add_argument("--dense-weight", type=float, default=1.0)
    parser.add_argument("--lexical-weight", type=float, default=1.0)
    parser.add_argument("--output")
    args = parser.parse_args()
    if args.candidate_limit < 5:
        parser.error("--candidate-limit 不能小于 5")

    cases = json.loads(Path(args.cases).read_text(encoding="utf-8"))
    if not isinstance(cases, list) or not cases:
        raise ValueError("评测集必须是非空 JSON 数组")
    ids = [str(case.get("id") or "") for case in cases]
    if any(not value for value in ids) or len(ids) != len(set(ids)):
        raise ValueError("评测样本 id 必须非空且唯一")

    cfg = load_rag_config()
    embedder = DashScopeEmbeddingClient(
        api_key=cfg.api_key, base_url=cfg.base_url,
        model=cfg.model, dimensions=cfg.dimensions,
    )
    store = QdrantRuleStore(QdrantClient(url=cfg.qdrant_url), cfg.collection, embedder)
    case_results = []
    details = []
    for index, case in enumerate(cases, start=1):
        if args.mode == "hybrid":
            raw = store.hybrid_search(
                str(case["query"]), language=str(case["language"]),
                category=case.get("category"), knowledge_version=cfg.knowledge_version,
                limit=args.candidate_limit, candidate_limit=args.candidate_limit,
                dense_weight=args.dense_weight, lexical_weight=args.lexical_weight,
            )
        else:
            raw = store.search(
                str(case["query"]), language=str(case["language"]),
                category=case.get("category"), knowledge_version=cfg.knowledge_version,
                limit=args.candidate_limit,
            )
        ranked = unique_rule_ranking(raw)
        ranked_ids = tuple(item.rule_id for item in ranked)
        relevant = tuple(str(value) for value in case["relevant_rule_ids"])
        result = RetrievalCaseResult(str(case["id"]), relevant, ranked_ids)
        case_results.append(result)
        first_rank = next((i for i, rule_id in enumerate(ranked_ids, 1) if rule_id in relevant), None)
        details.append({
            "id": case["id"], "query": case["query"],
            "relevant_rule_ids": list(relevant), "first_relevant_rank": first_rank,
            "top5_rule_ids": list(ranked_ids[:5]),
        })
        print(f"[{index:02d}/{len(cases)}] {case['id']}: rank={first_rank or '-'} top1={ranked_ids[0] if ranked_ids else '-'}")

    metrics = compute_retrieval_metrics(case_results)
    print("\n规则级检索指标")
    for name in ("recall@1", "recall@3", "recall@5", "hit@1", "hit@3", "hit@5", "mrr"):
        print(f"{name:>9}: {float(metrics[name]):.4f}")
    failures = [item for item in details if item["first_relevant_rank"] is None or item["first_relevant_rank"] > 5]
    print(f"Top5 未命中: {len(failures)}/{len(cases)}")

    report = {
        "embedding_model": cfg.model,
        "embedding_dimensions": cfg.dimensions,
        "collection": cfg.collection,
        "knowledge_version": cfg.knowledge_version,
        "candidate_limit": args.candidate_limit,
        "retrieval_mode": args.mode,
        "dense_weight": args.dense_weight,
        "lexical_weight": args.lexical_weight,
        "metrics": metrics,
        "failures": failures,
        "cases": details,
    }
    if args.output:
        output = Path(args.output)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(f"报告: {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
