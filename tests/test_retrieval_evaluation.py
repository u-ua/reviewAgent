from review_agent.rag.evaluation import (
    RetrievalCaseResult,
    compute_retrieval_metrics,
    unique_rule_ranking,
)
from review_agent.rag.models import RetrievedRule


def _result(rule_id, score):
    return RetrievedRule(
        rule_id=rule_id, title=rule_id, text="text", score=score,
        content_sha256="a" * 64, source="test", source_url="",
        category="security", severity="reference", knowledge_version="v1",
    )


def test_unique_rule_ranking_keeps_best_chunk_per_rule():
    ranked = unique_rule_ranking([_result("A", 0.8), _result("B", 0.7), _result("A", 0.9)])
    assert [(item.rule_id, item.score) for item in ranked] == [("A", 0.9), ("B", 0.7)]


def test_retrieval_metrics_support_multiple_relevant_rules():
    cases = [
        RetrievalCaseResult("one", ("A",), ("A", "B", "C")),
        RetrievalCaseResult("two", ("B", "D"), ("A", "B", "C", "D")),
    ]
    metrics = compute_retrieval_metrics(cases)
    assert metrics["recall@1"] == 0.5
    assert metrics["recall@3"] == 0.75
    assert metrics["recall@5"] == 1.0
    assert metrics["mrr"] == 0.75
