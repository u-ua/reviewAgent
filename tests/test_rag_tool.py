from __future__ import annotations

from dataclasses import dataclass

from review_agent.tools.rule_search import build_rule_search_tool
from review_agent.rag.models import RetrievedRule
from conftest import demo_repo_root, make_ctx


@dataclass
class FakeRuleStore:
    def search(self, query, *, language, category=None, limit=5):
        assert query == "SQL 拼接"
        assert language == "python"
        assert category == "security"
        assert limit == 5
        return [
            RetrievedRule(
                rule_id="CWE-89",
                title="SQL Injection",
                text="Use parameterized queries.",
                score=0.98,
                content_sha256="a" * 64,
                source="CWE",
                source_url="https://cwe.mitre.org/data/definitions/89.html",
                category="security",
                severity="high",
                knowledge_version="v1",
            )
        ]


def test_rule_search_writes_traceable_artifact():
    ctx = make_ctx(demo_repo_root(), ["src"], task_id="task:security")
    ctx.stores.ragStore = FakeRuleStore()
    result = build_rule_search_tool().execute(
        {"query": "SQL 拼接", "language": "python", "category": "security"},
        ctx,
    )
    assert result["ok"] is True
    assert result["rules"][0]["ruleId"] == "CWE-89"
    assert ctx.stores.artifactStore.has(result["artifactRef"])
    record = ctx.stores.artifactStore.get(result["artifactRef"])
    assert record.kind == "rule"


def test_rule_search_rejects_unconfigured_store():
    ctx = make_ctx(demo_repo_root(), ["src"])
    result = build_rule_search_tool().execute(
        {"query": "SQL 拼接", "language": "python"},
        ctx,
    )
    assert result["ok"] is False
    assert "未配置" in result["summary"]
