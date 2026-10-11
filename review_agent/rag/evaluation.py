"""规则级检索评测：对同一规则的多个分块去重后计算 Recall@K、Hit@K 与 MRR。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

from .models import RetrievedRule


@dataclass(frozen=True)
class RetrievalCaseResult:
    case_id: str
    relevant_rule_ids: tuple[str, ...]
    ranked_rule_ids: tuple[str, ...]


def unique_rule_ranking(results: Sequence[RetrievedRule]) -> list[RetrievedRule]:
    """同一 rule_id 只保留最高分分块，避免长文档凭分块数量占满 TopK。"""
    unique: list[RetrievedRule] = []
    seen: set[str] = set()
    for item in sorted(results, key=lambda value: value.score, reverse=True):
        if item.rule_id in seen:
            continue
        seen.add(item.rule_id)
        unique.append(item)
    return unique


def compute_retrieval_metrics(
    cases: Sequence[RetrievalCaseResult],
    *,
    ks: tuple[int, ...] = (1, 3, 5),
) -> dict[str, float | int]:
    if not cases:
        raise ValueError("检索评测集不能为空")
    if not ks or any(k < 1 for k in ks):
        raise ValueError("K 必须是正整数")

    totals = {k: 0.0 for k in ks}
    hits = {k: 0 for k in ks}
    reciprocal_rank = 0.0
    for case in cases:
        relevant = set(case.relevant_rule_ids)
        if not relevant:
            raise ValueError(f"样本 {case.case_id} 没有标准规则")
        for k in ks:
            retrieved = set(case.ranked_rule_ids[:k])
            matched = len(relevant & retrieved)
            totals[k] += matched / len(relevant)
            hits[k] += int(matched > 0)
        first_rank = next(
            (rank for rank, rule_id in enumerate(case.ranked_rule_ids, start=1) if rule_id in relevant),
            None,
        )
        if first_rank is not None:
            reciprocal_rank += 1.0 / first_rank

    count = len(cases)
    metrics: dict[str, float | int] = {"cases": count}
    for k in ks:
        metrics[f"recall@{k}"] = totals[k] / count
        metrics[f"hit@{k}"] = hits[k] / count
    metrics["mrr"] = reciprocal_rank / count
    return metrics
