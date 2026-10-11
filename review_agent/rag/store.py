"""Qdrant 规则库：维度校验、幂等入库、受过滤条件约束的检索。"""

from __future__ import annotations

import uuid
from collections.abc import Sequence

from qdrant_client import QdrantClient, models

from .embeddings import EmbeddingClient
from .hybrid import BM25RuleIndex, reciprocal_rank_fusion
from .models import RetrievedRule, RuleDocument


class QdrantRuleStore:
    def __init__(self, client: QdrantClient, collection: str, embedder: EmbeddingClient):
        self.client = client
        self.collection = collection
        self.embedder = embedder
        self._lexical_cache: dict[tuple[str, str | None, str], BM25RuleIndex] = {}

    def ensure_collection(self, *, create_payload_indexes: bool = False) -> None:
        if self.client.collection_exists(self.collection):
            info = self.client.get_collection(self.collection)
            vectors = info.config.params.vectors
            size = getattr(vectors, "size", None)
            if size != self.embedder.dimensions:
                raise ValueError(
                    f"Collection {self.collection} 维度为 {size}，"
                    f"当前模型要求 {self.embedder.dimensions}；请使用新 Collection"
                )
            return

        self.client.create_collection(
            collection_name=self.collection,
            vectors_config=models.VectorParams(
                size=self.embedder.dimensions,
                distance=models.Distance.COSINE,
            ),
        )
        if create_payload_indexes:
            for field in ("rule_id", "languages", "category", "severity", "source", "knowledge_version"):
                self.client.create_payload_index(
                    collection_name=self.collection,
                    field_name=field,
                    field_schema=models.PayloadSchemaType.KEYWORD,
                )
            self.client.create_payload_index(
                collection_name=self.collection,
                field_name="enabled",
                field_schema=models.PayloadSchemaType.BOOL,
            )

    @staticmethod
    def _point_id(rule: RuleDocument) -> str:
        key = f"{rule.rule_id}:{rule.knowledge_version}:{rule.content_sha256}"
        return str(uuid.uuid5(uuid.NAMESPACE_URL, key))

    def upsert_rules(self, rules: Sequence[RuleDocument]) -> int:
        items = list(rules)
        if not items:
            return 0
        self.ensure_collection()
        vectors = self.embedder.embed([rule.embedding_text for rule in items])
        points = [
            models.PointStruct(
                id=self._point_id(rule),
                vector=vector,
                payload=rule.to_payload(model=self.embedder.model, dimensions=self.embedder.dimensions),
            )
            for rule, vector in zip(items, vectors, strict=True)
        ]
        self.client.upsert(collection_name=self.collection, points=points, wait=True)
        return len(points)

    def search(
        self,
        query: str,
        *,
        language: str,
        category: str | None = None,
        knowledge_version: str = "v1",
        limit: int = 5,
        min_score: float | None = None,
    ) -> list[RetrievedRule]:
        if not query.strip():
            raise ValueError("检索 query 不能为空")
        must: list[models.Condition] = [
            models.FieldCondition(key="languages", match=models.MatchValue(value=language)),
            models.FieldCondition(key="knowledge_version", match=models.MatchValue(value=knowledge_version)),
            models.FieldCondition(key="enabled", match=models.MatchValue(value=True)),
        ]
        if category:
            must.append(models.FieldCondition(key="category", match=models.MatchValue(value=category)))
        vector = self.embedder.embed([query])[0]
        points = self.client.query_points(
            collection_name=self.collection,
            query=vector,
            query_filter=models.Filter(must=must),
            limit=limit,
            score_threshold=min_score,
            with_payload=True,
        ).points
        results: list[RetrievedRule] = []
        for point in points:
            payload = point.payload or {}
            results.append(
                RetrievedRule(
                    rule_id=str(payload["rule_id"]),
                    title=str(payload["title"]),
                    text=str(payload["text"]),
                    score=float(point.score),
                    content_sha256=str(payload["content_sha256"]),
                    source=str(payload["source"]),
                    source_url=str(payload.get("source_url") or ""),
                    category=str(payload["category"]),
                    severity=str(payload["severity"]),
                    knowledge_version=str(payload["knowledge_version"]),
                    chunk_id=str(payload.get("chunk_id") or ""),
                    section_type=str(payload.get("section_type") or ""),
                    source_version=str(payload.get("source_version") or ""),
                    source_file_sha256=str(payload.get("source_file_sha256") or ""),
                    source_chunk_sha256=str(payload.get("source_chunk_sha256") or ""),
                    heading_path=tuple(str(value) for value in (payload.get("heading_path") or [])),
                )
            )
        return results

    def _payload_documents(
        self,
        *,
        language: str,
        category: str | None,
        knowledge_version: str,
    ) -> list[RetrievedRule]:
        must: list[models.Condition] = [
            models.FieldCondition(key="languages", match=models.MatchValue(value=language)),
            models.FieldCondition(key="knowledge_version", match=models.MatchValue(value=knowledge_version)),
            models.FieldCondition(key="enabled", match=models.MatchValue(value=True)),
        ]
        if category:
            must.append(models.FieldCondition(key="category", match=models.MatchValue(value=category)))
        offset = None
        documents: list[RetrievedRule] = []
        while True:
            points, offset = self.client.scroll(
                collection_name=self.collection,
                scroll_filter=models.Filter(must=must),
                limit=256,
                offset=offset,
                with_payload=True,
                with_vectors=False,
            )
            for point in points:
                payload = point.payload or {}
                documents.append(
                    RetrievedRule(
                        rule_id=str(payload["rule_id"]), title=str(payload["title"]),
                        text=str(payload["text"]), score=0.0,
                        content_sha256=str(payload["content_sha256"]),
                        source=str(payload["source"]), source_url=str(payload.get("source_url") or ""),
                        category=str(payload["category"]), severity=str(payload["severity"]),
                        knowledge_version=str(payload["knowledge_version"]),
                        chunk_id=str(payload.get("chunk_id") or ""),
                        section_type=str(payload.get("section_type") or ""),
                        source_version=str(payload.get("source_version") or ""),
                        source_file_sha256=str(payload.get("source_file_sha256") or ""),
                        source_chunk_sha256=str(payload.get("source_chunk_sha256") or ""),
                        heading_path=tuple(str(value) for value in (payload.get("heading_path") or [])),
                    )
                )
            if offset is None:
                break
        return documents

    def hybrid_search(
        self,
        query: str,
        *,
        language: str,
        category: str | None = None,
        knowledge_version: str = "v1",
        limit: int = 5,
        candidate_limit: int = 50,
        dense_weight: float = 1.0,
        lexical_weight: float = 1.0,
    ) -> list[RetrievedRule]:
        dense = self.search(
            query, language=language, category=category,
            knowledge_version=knowledge_version, limit=candidate_limit,
        )
        cache_key = (language, category, knowledge_version)
        lexical = self._lexical_cache.get(cache_key)
        if lexical is None:
            lexical = BM25RuleIndex(
                self._payload_documents(
                    language=language, category=category,
                    knowledge_version=knowledge_version,
                )
            )
            self._lexical_cache[cache_key] = lexical
        sparse = lexical.search(query, limit=candidate_limit)
        return reciprocal_rank_fusion(
            [dense, sparse], limit=limit,
            weights=[dense_weight, lexical_weight],
        )
