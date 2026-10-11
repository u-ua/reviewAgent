"""report.py：生成 review.md 并计算评测三数字（对应 src/report.ts）。"""

from __future__ import annotations

from pathlib import Path

LINE_TOLERANCE = 1


def _refs(f) -> list[str]:
    if isinstance(f, dict):
        return f.get("evidenceRefs") or []
    return f.evidenceRefs or []


def _rule_refs(f) -> list[str]:
    if isinstance(f, dict):
        return f.get("ruleEvidenceRefs") or []
    return getattr(f, "ruleEvidenceRefs", None) or []


def _path(f):
    return f.get("path") if isinstance(f, dict) else f.path


def _start(f):
    return f.get("startLine") if isinstance(f, dict) else f.startLine


def _is_number(v) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def compute_metrics(findings: list, cases: list | None) -> dict:
    """评测三数字：用标准答案逐条对 Findings（与 src/report.ts computeMetrics 对齐）。

    findings 兼容 Finding dataclass 或 findings.json 里的 dict；
    cases 为 ReviewCase dict 列表。scripts/evaluate.py 复用的就是本函数。
    """
    no_evidence = sum(1 for f in findings if len(_refs(f)) == 0)

    if not cases or len(cases) == 0:
        return {"hits": 0, "falsePositives": len(findings), "noEvidence": no_evidence, "totalCases": 0}

    hit_case_idx: set[int] = set()
    for f in findings:
        path = _path(f)
        start = _start(f)
        if not _is_number(start):
            continue
        for i, c in enumerate(cases):
            if i in hit_case_idx:
                continue
            if c["path"] == path and abs(c["startLine"] - start) <= LINE_TOLERANCE:
                hit_case_idx.add(i)
                break

    matched_findings = sum(
        1
        for f in findings
        if _is_number(_start(f))
        and any(c["path"] == _path(f) and abs(c["startLine"] - _start(f)) <= LINE_TOLERANCE for c in cases)
    )

    return {
        "hits": len(hit_case_idx),
        "falsePositives": len(findings) - matched_findings,
        "noEvidence": no_evidence,
        "totalCases": len(cases),
    }


def _config(value, key: str):
    """config 可能是 ReviewRunConfig dataclass 或 dict，统一访问。"""
    return value[key] if isinstance(value, dict) else getattr(value, key)


def generate_review_markdown(*, config, findings, tasks, outcomes, cases, artifact_store) -> str:
    """生成 Markdown 报告正文。"""
    metrics = compute_metrics(findings, cases)

    lines: list[str] = []
    lines.append("# 代码审查报告")
    lines.append("")
    lines.append(f"- 审查目标：{_config(config, 'goal')}")
    lines.append(f"- 审查范围：{'整个仓库' if len(_config(config, 'scope')) == 0 else ', '.join(_config(config, 'scope'))}")
    lines.append(f"- Provider：{_config(config, 'provider')}")
    lines.append(f"- 任务数：{len(tasks)}，交卷：{len(outcomes)}")
    lines.append(
        f"- 评测：命中 {metrics['hits']} / 误报 {metrics['falsePositives']} / 无证据 {metrics['noEvidence']}"
        f"（标准答案 {metrics['totalCases']} 条）"
    )
    lines.append("")

    if len(tasks) > 0:
        lines.append("## 任务图")
        lines.append("")
        lines.append("| 任务 | 状态 | 目标 |")
        lines.append("|---|---|---|")
        for t in tasks:
            lines.append(f"| {t.taskId} | {t.status} | {t.goal} |")
        lines.append("")

    if len(outcomes) > 0:
        lines.append("## 交卷记录")
        lines.append("")
        for o in outcomes:
            lines.append(f"- **{o.result.taskId}** → `{o.result.status}`：{o.result.summary}")
        lines.append("")

    lines.append(f"## Findings（{len(findings)} 条）")
    lines.append("")
    if len(findings) == 0:
        lines.append("_未发现明确问题。_")
    for severity in ("critical", "high", "medium", "low"):
        group = [f for f in findings if (_severity(f)) == severity]
        if len(group) == 0:
            continue
        lines.append(f"### {severity.upper()}")
        lines.append("")
        for f in group:
            lines.append(f"#### {_title(f)}")
            lines.append("")
            lines.append(f"- 位置：`{_path(f)}:{_start(f)}-{_end(f)}`")
            lines.append(f"- 依据：{_rationale(f)}")
            lines.append(f"- 建议：{_suggestion(f)}")
            for ref in _refs(f):
                record = artifact_store.get(ref)
                preview = record.preview if record else "(证据缺失)"
                excerpt = preview.replace("\r\n", " ").replace("\n", " ")[:200]
                lines.append(f"- 证据：`{ref}` {'（' + str(record.byteLength) + ' 字节）' if record else ''}")
                lines.append("  ```text")
                lines.append(f"  {excerpt}")
                lines.append("  ```")
            for ref in _rule_refs(f):
                record = artifact_store.get(ref)
                preview = record.preview if record else "(规则证据缺失)"
                excerpt = preview.replace("\r\n", " ").replace("\n", " ")[:200]
                lines.append(f"- 规则证据：`{ref}` {'（' + str(record.byteLength) + ' 字节）' if record else ''}")
                lines.append("  ```json")
                lines.append(f"  {excerpt}")
                lines.append("  ```")
            lines.append("")
    return "\n".join(lines)


def _severity(f) -> str:
    return f["severity"] if isinstance(f, dict) else f.severity


def _title(f) -> str:
    return f["title"] if isinstance(f, dict) else f.title


def _end(f) -> int:
    return f["endLine"] if isinstance(f, dict) else f.endLine


def _rationale(f) -> str:
    return f["rationale"] if isinstance(f, dict) else f.rationale


def _suggestion(f) -> str:
    return f["suggestion"] if isinstance(f, dict) else f.suggestion


def write_report(*, session_dir: str, config, findings, tasks, outcomes, cases, artifact_store):
    """写 review.md，返回 report 路径与评测数字。"""
    markdown = generate_review_markdown(
        config=config,
        findings=findings,
        tasks=tasks,
        outcomes=outcomes,
        cases=cases,
        artifact_store=artifact_store,
    )
    report_path = Path(session_dir) / "review.md"
    report_path.write_text(markdown, encoding="utf-8")
    return str(report_path), compute_metrics(findings, cases)
