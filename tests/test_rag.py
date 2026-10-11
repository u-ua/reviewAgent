from __future__ import annotations

import json
from pathlib import Path

import pytest
from qdrant_client import QdrantClient

from review_agent.rag.config import load_rag_config
from review_agent.rag.loader import load_rules
from review_agent.rag.models import RuleDocument
from review_agent.rag.store import QdrantRuleStore


class FakeEmbeddingClient:
    model = "fake-embedding-v1"
    dimensions = 3

    def embed(self, texts):
        vectors = []
        for text in texts:
            lower = text.lower()
            if "sql" in lower or "注入" in lower:
                vectors.append([1.0, 0.0, 0.0])
            elif "html" in lower or "xss" in lower:
                vectors.append([0.0, 1.0, 0.0])
            else:
                vectors.append([0.0, 0.0, 1.0])
        return vectors


def make_rule(**overrides):
    data = {
        "rule_id": "CWE-89",
        "title": "SQL Injection",
        "text": "SQL 字符串拼接可能导致注入",
        "languages": ["python"],
        "category": "security",
        "severity": "high",
        "source": "CWE",
        "source_url": "https://cwe.mitre.org/data/definitions/89.html",
        "knowledge_version": "v1",
    }
    data.update(overrides)
    return RuleDocument.from_dict(data)


def test_rule_hash_is_stable_and_content_addressed():
    first = make_rule()
    reordered = RuleDocument.from_dict(dict(reversed(list(first.hash_payload().items()))))
    changed = make_rule(text="不同内容")
    assert first.content_sha256 == reordered.content_sha256
    assert first.content_sha256 != changed.content_sha256


def test_loader_rejects_duplicate_rule_ids(tmp_path: Path):
    data = [make_rule().hash_payload(), make_rule(title="duplicate").hash_payload()]
    path = tmp_path / "rules.json"
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    with pytest.raises(ValueError, match="必须唯一"):
        load_rules(path)


def test_qdrant_upsert_is_idempotent_and_search_is_filtered():
    client = QdrantClient(":memory:")
    store = QdrantRuleStore(client, "rules", FakeEmbeddingClient())
    python_rule = make_rule()
    java_rule = make_rule(
        rule_id="JAVA-XSS",
        title="XSS",
        text="HTML XSS output",
        languages=["java"],
    )
    assert store.upsert_rules([python_rule, java_rule]) == 2
    assert store.upsert_rules([python_rule, java_rule]) == 2
    assert client.count("rules", exact=True).count == 2

    results = store.search("SQL 注入", language="python", category="security")
    assert [item.rule_id for item in results] == ["CWE-89"]
    assert results[0].content_sha256 == python_rule.content_sha256


def test_disabled_and_wrong_version_rules_are_not_returned():
    client = QdrantClient(":memory:")
    store = QdrantRuleStore(client, "rules", FakeEmbeddingClient())
    store.upsert_rules(
        [
            make_rule(rule_id="DISABLED", enabled=False),
            make_rule(rule_id="OLD", knowledge_version="v0"),
        ]
    )
    assert store.search("SQL 注入", language="python", knowledge_version="v1") == []


def test_existing_collection_dimension_mismatch_is_rejected():
    client = QdrantClient(":memory:")
    first = QdrantRuleStore(client, "rules", FakeEmbeddingClient())
    first.ensure_collection()

    class OtherEmbedding(FakeEmbeddingClient):
        dimensions = 4

    with pytest.raises(ValueError, match="请使用新 Collection"):
        QdrantRuleStore(client, "rules", OtherEmbedding()).ensure_collection()


def test_rag_config_does_not_require_openai_key():
    cfg = load_rag_config(
        {
            "DASHSCOPE_API_KEY": "secret-value",
            "EMBEDDING_PROVIDER": "dashscope",
            "EMBEDDING_MODEL": "text-embedding-v4",
            "EMBEDDING_DIMENSIONS": "1024",
            "QDRANT_URL": "http://localhost:6333",
            "QDRANT_COLLECTION": "review_rules_v1",
        },
        load_dotenv=False,
    )
    assert cfg.model == "text-embedding-v4"
    assert cfg.dimensions == 1024
    assert cfg.api_key == "secret-value"
