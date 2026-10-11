from review_agent.rag.hybrid import BM25RuleIndex, expand_security_query, reciprocal_rank_fusion
from review_agent.rag.models import RetrievedRule


def _rule(rule_id, text, score=0.0):
    return RetrievedRule(
        rule_id=rule_id, title=rule_id, text=text, score=score,
        content_sha256="a" * 64, source="test", source_url="",
        category="security", severity="reference", knowledge_version="v1",
    )


def test_query_expansion_adds_cross_language_authorization_terms():
    expanded = expand_security_query("没有验证订单是否属于当前用户")
    assert "authorization" in expanded
    assert "ownership" in expanded


def test_bm25_finds_authorization_rule_after_expansion():
    index = BM25RuleIndex([
        _rule("CWE-862", "Missing Authorization access control ownership check"),
        _rule("CWE-89", "SQL query injection parameterized statements"),
    ])
    assert index.search("没有验证资源归属和权限")[0].rule_id == "CWE-862"


def test_bm25_deduplicates_before_applying_limit():
    index = BM25RuleIndex([
        _rule("A", "authorization ownership"),
        _rule("A", "authorization ownership access control"),
        _rule("B", "authorization check"),
    ])
    assert [item.rule_id for item in index.search("authorization", limit=2)] == ["A", "B"]


def test_rrf_deduplicates_rule_chunks_and_combines_rankings():
    dense = [_rule("A", "one", 0.9), _rule("A", "two", 0.8), _rule("B", "three", 0.7)]
    lexical = [_rule("B", "three", 8.0), _rule("C", "four", 7.0)]
    fused = reciprocal_rank_fusion([dense, lexical], limit=3)
    assert fused[0].rule_id == "B"
    assert len({item.rule_id for item in fused}) == 3


def test_rrf_supports_explicit_channel_weights():
    dense = [_rule("A", "dense", 0.9), _rule("B", "dense", 0.8)]
    lexical = [_rule("B", "lexical", 9.0), _rule("A", "lexical", 8.0)]
    fused = reciprocal_rank_fusion([dense, lexical], weights=[1.0, 2.0])
    assert fused[0].rule_id == "B"
