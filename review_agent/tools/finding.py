"""finding_write：审查结论的写入门卫（对应 src/tools/finding-tools.ts）。

无行号、源码证据无效，或 RAG 模式下缺少规则证据 → 整条拒绝，让模型重试。
"""

from __future__ import annotations

from ..scope import assert_in_scope
from ..types import Finding, Tool, ToolParam

SEVERITIES = ("critical", "high", "medium", "low")


def _fail(message: str, reason: str = "validation_error") -> dict:
    """返回给模型的说明可读；入账只使用 reason，避免泄露提交中的敏感内容。"""
    return {"ok": False, "summary": f"Finding 被拒绝: {message}", "error": message, "rejectionReason": reason}


def _is_integer_value(v) -> bool:
    """对齐 TS 的 Number.isInteger：接受 11 / 11.0，拒绝 1.5、true。"""
    if isinstance(v, bool):
        return False
    if isinstance(v, int):
        return True
    return isinstance(v, float) and v.is_integer()


def _finding_write_execute(args, ctx) -> dict:
    finding_id = args.get("id")
    severity = args.get("severity")
    path = args.get("path")
    start_line = args.get("startLine")
    end_line = args.get("endLine")
    title = args.get("title")
    rationale = args.get("rationale")
    suggestion = args.get("suggestion")
    evidence_refs = args.get("evidenceRefs") or []
    rule_evidence_refs = args.get("ruleEvidenceRefs") or []
    requested_dimension = args.get("dimension")
    task_dimension = ctx.taskDimension

    # 逐条门卫
    if not finding_id or not isinstance(finding_id, str):
        return _fail("缺少 id")
    if severity not in SEVERITIES:
        return _fail(f"severity 必须是 {'/'.join(SEVERITIES)}")
    if not isinstance(path, str) or len(path) == 0:
        return _fail("缺少 path")
    if not _is_integer_value(start_line) or start_line < 1:
        return _fail("startLine 必须是 ≥1 的整数")
    if not _is_integer_value(end_line) or end_line < 1:
        return _fail("endLine 必须是 ≥1 的整数")
    if end_line < start_line:
        return _fail(f"endLine({end_line}) 不能小于 startLine({start_line})")
    if not title or not isinstance(title, str):
        return _fail("缺少 title")
    if not rationale or not isinstance(rationale, str):
        return _fail("缺少 rationale")
    if not suggestion or not isinstance(suggestion, str):
        return _fail("缺少 suggestion")
    if requested_dimension is not None and requested_dimension != task_dimension:
        return _fail(f"Finding dimension ({requested_dimension}) 与任务维度 ({task_dimension}) 不一致")
    if not isinstance(evidence_refs, list) or len(evidence_refs) == 0:
        return _fail("evidenceRefs 不能为空：必须引用 read_file/git_diff 的证据", "missing_evidence")
    for ref in evidence_refs:
        if not isinstance(ref, str):
            return _fail("evidenceRefs 必须是字符串数组", "invalid_evidence")
        if not ctx.stores.artifactStore.has(ref):
            return _fail("证据引用不存在（先 read_file/git_diff 再引用它的 artifact）", "missing_evidence")
        record = ctx.stores.artifactStore.get(ref)
        if record is None or record.kind not in ("code", "diff"):
            return _fail("源码证据类型非法（必须来自 read_file/git_diff）", "invalid_evidence")

    # 仅凭“读过某个 Artifact”仍不足以约束模型的行号。Finding 的文件与行范围
    # 必须落在至少一份 read_file 生成的同文件代码证据内。diff 仍可作为补充证据，
    # 但不单独承担行号校验，避免误把补丁上下文当成完整源码范围。
    has_matching_code_range = False
    for ref in evidence_refs:
        record = ctx.stores.artifactStore.get(ref)
        if record is None or record.kind != "code":
            continue
        if (
            record.sourcePath == path
            and record.sourceStartLine is not None
            and record.sourceEndLine is not None
            and record.sourceStartLine <= start_line <= end_line <= record.sourceEndLine
        ):
            has_matching_code_range = True
            break
    if not has_matching_code_range:
        return _fail(
            "Finding 的文件或行号未被 read_file 证据覆盖",
            "line_outside_evidence",
        )

    rag_enabled = ctx.stores.ragStore is not None
    if not isinstance(rule_evidence_refs, list):
        return _fail("ruleEvidenceRefs 必须是字符串数组", "invalid_rule_evidence")
    if rag_enabled and task_dimension == "security" and len(rule_evidence_refs) == 0:
        return _fail("RAG 模式下 ruleEvidenceRefs 不能为空：必须先调用 search_review_rules", "missing_rule_evidence")
    for ref in rule_evidence_refs:
        if not isinstance(ref, str):
            return _fail("ruleEvidenceRefs 必须是字符串数组", "invalid_rule_evidence")
        record = ctx.stores.artifactStore.get(ref)
        if record is None:
            return _fail("规则证据引用不存在", "missing_rule_evidence")
        if record.kind != "rule":
            return _fail("规则证据类型非法（必须来自 search_review_rules）", "invalid_rule_evidence")

    # path 必须在审查范围内（且是真实存在的文件）
    try:
        assert_in_scope(ctx.repoRoot, ctx.scope, path)
    except Exception as e:
        return _fail(str(e))

    finding = Finding(
        id=finding_id,
        severity=severity,
        path=path,
        startLine=start_line,
        endLine=end_line,
        title=title,
        rationale=rationale,
        suggestion=suggestion,
        evidenceRefs=evidence_refs,
        taskId=ctx.taskId,
        ruleEvidenceRefs=rule_evidence_refs,
        # 不信任模型自行选择维度：缺失时补全，有值也已校验必须相同。
        dimension=task_dimension,
    )
    ctx.stores.findingStore.add(finding)
    return {"ok": True, "summary": f"已记录 Finding {finding_id}: {title} @ {path}:{start_line}"}


def build_finding_write_tool() -> Tool:
    return Tool(
        name="finding_write",
        description=(
            "写一条审查结论。evidenceRefs 必须引用 read_file/git_diff 产生的源码证据；"
            "security 维度启用 RAG 时，ruleEvidenceRefs 还必须引用 search_review_rules 产生的规则证据；"
            "两类证据不能混用。"
        ),
        parameters=[
            ToolParam("id", "string", "Finding 唯一 id，如 finding-001", True),
            ToolParam("severity", "string", "critical|high|medium|low", True),
            ToolParam("path", "string", "相对仓库根的文件路径", True),
            ToolParam("startLine", "number", "缺陷起始行", True),
            ToolParam("endLine", "number", "缺陷结束行", True),
            ToolParam("title", "string", "一句话标题", True),
            ToolParam("rationale", "string", "为什么是问题（依据）", True),
            ToolParam("suggestion", "string", "期望建议", True),
            ToolParam("evidenceRefs", "array", "证据 artifact 引用列表（来自 read_file/git_diff）", True, itemType="string"),
            ToolParam("dimension", "string", "可选；若提供必须与任务单维度一致", False),
            ToolParam(
                "ruleEvidenceRefs",
                "array",
                "规则证据引用列表（security + RAG 时必须来自 search_review_rules）",
                False,
                itemType="string",
            ),
        ],
        execute=_finding_write_execute,
    )
