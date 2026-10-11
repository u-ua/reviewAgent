"""search_review_rules：Executor 唯一可用的规则知识库入口。"""

from __future__ import annotations

import json

from ..types import Tool, ToolParam


def _search_review_rules_execute(args, ctx) -> dict:
    if ctx.stores.ragStore is None:
        return {
            "ok": False,
            "summary": "规则知识库未配置",
            "error": "RAG store unavailable",
        }
    query = args.get("query") or ""
    language = (args.get("language") or "").lower()
    category = args.get("category") or None
    if not query.strip() or not language.strip():
        return {"ok": False, "summary": "query 和 language 不能为空", "error": "invalid query"}

    hybrid_search = getattr(ctx.stores.ragStore, "hybrid_search", None)
    if callable(hybrid_search):
        results = hybrid_search(query, language=language, category=category, limit=5)
        retrieval_mode = "hybrid"
    else:
        results = ctx.stores.ragStore.search(
            query, language=language, category=category, limit=5,
        )
        retrieval_mode = "dense"
    evidence = {
        "query": query,
        "language": language,
        "category": category,
        "retrievalMode": retrieval_mode,
        "results": [
            {
                "ruleId": item.rule_id,
                "title": item.title,
                "text": item.text,
                "score": item.score,
                "contentSha256": item.content_sha256,
                "source": item.source,
                "sourceUrl": item.source_url,
                "severity": item.severity,
                "knowledgeVersion": item.knowledge_version,
                "chunkId": item.chunk_id,
                "sectionType": item.section_type,
                "sourceVersion": item.source_version,
                "sourceFileSha256": item.source_file_sha256,
                "sourceChunkSha256": item.source_chunk_sha256,
                "headingPath": list(item.heading_path),
            }
            for item in results
        ],
    }
    artifact = ctx.stores.artifactStore.write(
        task_id=ctx.taskId or "task:unknown",
        kind="rule",
        media_type="application/json",
        content=json.dumps(evidence, ensure_ascii=False, sort_keys=True, indent=2),
        preview_length=1200,
    )
    return {
        "ok": True,
        "summary": f"检索到 {len(results)} 条审查规则",
        "artifactRef": artifact.artifactRef,
        "rules": evidence["results"],
    }


def build_rule_search_tool() -> Tool:
    return Tool(
        name="search_review_rules",
        description=(
            "从受控规则知识库检索与当前代码行为相关的审查规则。"
            "返回的规则会固化为 SHA-256 Artifact，Finding 应同时引用代码和规则证据。"
        ),
        parameters=[
            ToolParam("query", "string", "代码行为摘要或待验证风险", True),
            ToolParam("language", "string", "源码语言，如 python/typescript", True),
            ToolParam("category", "string", "可选规则分类，如 security/reliability", False),
        ],
        execute=_search_review_rules_execute,
    )
