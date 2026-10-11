"""从运行账本生成可审计的静态 JSON/Markdown 报告（不调用 LLM）。"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from collections import Counter
from pathlib import Path
from typing import Any

from review_agent.metrics import build_metrics


DIMENSIONS = ("security", "performance", "logic")


class AuditLogError(ValueError):
    pass


def _load_json(path: Path, warnings: list[str], default: Any) -> Any:
    if not path.exists():
        warnings.append(f"辅助产物缺失：{path.name}")
        return default
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
        return value
    except (OSError, json.JSONDecodeError) as exc:
        warnings.append(f"辅助产物无法读取：{path.name}（{exc}）")
        return default


def load_events(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        raise AuditLogError(f"找不到审计日志：{path}")
    events = []
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        try:
            event = json.loads(line)
        except json.JSONDecodeError as exc:
            raise AuditLogError(f"审计日志第 {number} 行 JSON 损坏：{exc.msg}") from exc
        if not isinstance(event, dict):
            raise AuditLogError(f"审计日志第 {number} 行必须是 JSON 对象")
        events.append(event)
    return events


def _na(value: Any) -> str:
    return "N/A" if value is None else str(value)


def _safe_artifact_path(session: Path, ref: str) -> dict[str, Any] | None:
    if not isinstance(ref, str) or not ref.startswith("artifact:"):
        return None
    digest = ref.removeprefix("artifact:")
    if len(digest) != 64 or any(c not in "0123456789abcdef" for c in digest.lower()):
        return None
    matches = list((session / "artifacts").glob(f"**/{digest}.*")) if (session / "artifacts").exists() else []
    if not matches:
        return None
    file = matches[0]
    try:
        actual = hashlib.sha256(file.read_bytes()).hexdigest()
        relative = file.relative_to(session).as_posix()
    except OSError:
        return None
    return {"path": relative, "byteLength": file.stat().st_size, "sha256": actual, "hashMatchesRef": actual == digest}


def _event_warnings(events: list[dict[str, Any]]) -> list[str]:
    warnings = []
    expected = 1
    required = {"id", "seq", "role", "eventType", "summary", "artifactRefs"}
    for index, event in enumerate(events, 1):
        if not required.issubset(event):
            warnings.append(f"事件 #{index} 缺少字段：{', '.join(sorted(required - set(event)))}")
        if not isinstance(event.get("seq"), int):
            warnings.append(f"事件 #{index} 的 seq 非整数")
        elif event["seq"] != expected:
            warnings.append(f"JSONL seq 不连续：期望 {expected}，实际 {event['seq']}")
            expected = event["seq"]
        expected += 1
    return warnings


def _findings(events: list[dict[str, Any]], persisted: list[Any], session: Path, warnings: list[str]) -> dict[str, list[dict[str, Any]]]:
    persisted_by_id = {x.get("id"): x for x in persisted if isinstance(x, dict) and isinstance(x.get("id"), str)}
    accepted = [e for e in events if e.get("eventType") == "finding_accepted"]
    event_ids = []
    grouped = {dimension: [] for dimension in DIMENSIONS}
    persisted_ids = [x.get("id") for x in persisted if isinstance(x, dict) and isinstance(x.get("id"), str)]
    for fid, count in Counter(persisted_ids).items():
        if count > 1: warnings.append(f"findings.json 中重复 Finding ID：{fid}（{count} 次）")
    sources: list[tuple[dict[str, Any], dict[str, Any]]] = []
    if accepted:
        sources = [(event, ((event.get("payload") or {}).get("args") or {})) for event in accepted]
    elif persisted:
        warnings.append("legacy fallback：无法从JSONL证明提交事件")
        # 历史 session 没有 finding_accepted 时，保留 findings.json 的结论，明确降级语义。
        sources = [({}, finding) for finding in persisted if isinstance(finding, dict)]
    for event, args in sources:
        fid = args.get("id")
        if event and isinstance(fid, str): event_ids.append(fid)
        finding = persisted_by_id.get(fid, args)
        dimension = finding.get("dimension") or args.get("dimension") or (event.get("payload") or {}).get("dimension") or "unknown"
        refs = finding.get("evidenceRefs") or []
        rule_refs = finding.get("ruleEvidenceRefs") or []
        evidence = []
        for ref in [*refs, *rule_refs]:
            record = _safe_artifact_path(session, ref)
            evidence.append({"ref": ref, "exists": record is not None, "artifact": record})
            if record is None: warnings.append(f"Finding {fid or '(无 ID)'} 引用的 Artifact 不存在：{ref}")
        item = {"id": fid, "severity": finding.get("severity") or args.get("severity"), "path": finding.get("path") or args.get("path"), "startLine": finding.get("startLine") or args.get("startLine"), "endLine": finding.get("endLine") or args.get("endLine"), "title": finding.get("title") or args.get("title"), "rationale": finding.get("rationale"), "suggestion": finding.get("suggestion"), "evidenceRefs": refs, "ruleEvidenceRefs": rule_refs, "evidence": evidence}
        grouped.setdefault(dimension, []).append(item)
    for fid, count in Counter(event_ids).items():
        if count > 1: warnings.append(f"重复 Finding ID：{fid}（{count} 次）")
    return grouped


def build_report(session_dir: str | Path) -> dict[str, Any]:
    session = Path(session_dir).resolve()
    warnings: list[str] = []
    events = load_events(session / "execution.jsonl")
    warnings.extend(_event_warnings(events))
    tasks = _load_json(session / "tasks.json", warnings, [])
    persisted = _load_json(session / "findings.json", warnings, [])
    if not isinstance(tasks, list): warnings.append("tasks.json 必须是数组"); tasks = []
    if not isinstance(persisted, list): warnings.append("findings.json 必须是数组"); persisted = []
    task_ids = {t.get("taskId") for t in tasks if isinstance(t, dict)}
    for event in events:
        task_id = event.get("taskId")
        if task_id and task_id not in task_ids: warnings.append(f"事件引用不存在的 taskId：{task_id}")
    starts = [e for e in events if e.get("eventType") == "run_started"]
    finishes = [e for e in events if e.get("eventType") in ("run_finished", "goal_completed")]
    first_payload = (starts[0].get("payload") or {}) if starts else {}
    llm = [e.get("payload") or {} for e in events if e.get("eventType") == "llm_call"]
    outcomes = {}
    for e in events:
        if e.get("eventType") == "submit" and e.get("role") == "executor":
            args = ((e.get("payload") or {}).get("args") or {})
            outcomes[e.get("taskId")] = {"status": args.get("status"), "blockerReason": args.get("blockerReason")}
    metrics = build_metrics(events)
    provider = "fake" if llm and all(p.get("synthetic") for p in llm) else None
    findings = _findings(events, persisted, session, warnings)
    task_durations: dict[str, int] = {}
    task_starts: dict[tuple[str, str | None], int] = {}
    for event in events:
        task_id, elapsed = event.get("taskId"), event.get("elapsedMs")
        key = (task_id, event.get("epochId"))
        if isinstance(task_id, str) and isinstance(elapsed, int) and event.get("eventType") == "task_started":
            task_starts[key] = elapsed
        elif isinstance(task_id, str) and isinstance(elapsed, int) and event.get("eventType") == "task_finished" and key in task_starts:
            task_durations[task_id] = max(0, elapsed - task_starts[key])
    task_rows = []
    for task in tasks:
        if not isinstance(task, dict): continue
        task_rows.append({"taskId": task.get("taskId"), "dimension": task.get("dimension"), "goal": task.get("goal"), "status": task.get("status"), "dependsOnTaskRefs": task.get("dependsOnTaskRefs") or [], "executorSubmission": outcomes.get(task.get("taskId")), "durationMs": task_durations.get(task.get("taskId"))})
    timeline_types = {"decision_applied", "task_started", "task_finished", "finding_accepted", "finding_rejected", "tool_access_decision", "submit", "run_started", "run_finished", "goal_completed"}
    timeline = [{"seq": e.get("seq"), "elapsedMs": e.get("elapsedMs"), "eventType": e.get("eventType"), "role": e.get("role"), "taskId": e.get("taskId"), "summary": e.get("summary")} for e in sorted(events, key=lambda x: x.get("seq", 10**18)) if e.get("eventType") in timeline_types]
    interceptions = [{"type": (e.get("payload") or {}).get("reason"), "elapsedMs": e.get("elapsedMs"), "role": e.get("role"), "tool": (e.get("payload") or {}).get("tool"), "reason": "已由运行时拒绝"} for e in events if e.get("eventType") == "tool_access_decision" and (e.get("payload") or {}).get("allowed") is False]
    return {"schemaVersion": 1, "source": {"auditLog": "execution.jsonl", "readOnly": True}, "session": {"goal": (starts[0].get("summary", "").removeprefix("审查目标：") if starts else None), "repository": None, "scope": first_payload.get("scope"), "provider": provider, "models": sorted({p.get("model") for p in llm if p.get("model")}), "ragEnabled": any(e.get("eventType") == "tool_call" and (e.get("payload") or {}).get("tool") == "search_review_rules" for e in events), "startedElapsedMs": starts[0].get("elapsedMs") if starts else None, "endedElapsedMs": finishes[-1].get("elapsedMs") if finishes else None, "durationMs": metrics["durationsMs"]["session"], "finalStatus": finishes[-1].get("summary") if finishes else None}, "tasks": task_rows, "findings": findings, "authorizationInterceptions": interceptions, "metrics": metrics, "timeline": timeline, "integrity": {"warnings": list(dict.fromkeys(warnings)), "eventCount": len(events)}}


def render_markdown(report: dict[str, Any]) -> str:
    s, m = report["session"], report["metrics"]
    lines = ["# 审计静态报告", "", "## 会话概览", "", f"- 审查目标：{_na(s['goal'])}", f"- Scope：{', '.join(s['scope'] or []) if s['scope'] is not None else 'N/A'}", f"- Provider：{_na(s['provider'])}；模型：{', '.join(s['models']) or 'N/A'}", f"- RAG：{'是' if s['ragEnabled'] else '否'}；总耗时：{_na(s['durationMs'])} ms", f"- 最终状态：{_na(s['finalStatus'])}", "", "## 关键指标", "", "| 问题数 | 有效证据率 | 越权拦截率 | 平均任务耗时 | LLM 调用 | Token | 成本 |", "|---:|---:|---:|---:|---:|---:|---:|", f"| {m['findings']['total']} | {_na(m['evidenceValidity']['rate'])} | {_na(m['authorizationInterception']['rate'])} | {_na(m['durationsMs']['averageTask'])} ms | {m['tokens']['successfulCalls']} | {_na(m['tokens']['totalTokens'])} | {_na(m['cost']['total'])} |", "", "## 任务概览", "", "| taskId | dimension | goal | 状态 | 依赖 | Executor 交卷 | 耗时 |", "|---|---|---|---|---|---|---:|"]
    for t in report['tasks']: lines.append(f"| {t['taskId']} | {t['dimension']} | {t['goal']} | {t['status']} | {', '.join(t['dependsOnTaskRefs'])} | {(t['executorSubmission'] or {}).get('status', 'N/A')} | {_na(t['durationMs'])} |")
    for dimension in [*DIMENSIONS, *sorted(x for x in report['findings'] if x not in DIMENSIONS)]:
        lines += ["", f"## Findings — {dimension}", ""]
        values = report['findings'].get(dimension, [])
        if not values: lines.append("无 Findings。")
        for f in values: lines += [f"### [{f['severity']}] {f['title']}", f"- 位置：`{f['path']}:{f['startLine']}`", f"- 依据：{_na(f['rationale'])}", f"- 建议：{_na(f['suggestion'])}", f"- 源码证据：{', '.join(f['evidenceRefs']) or 'N/A'}", f"- 规则证据：{', '.join(f['ruleEvidenceRefs']) or 'N/A'}"]
    lines += ["", "## 权限与协议拦截", "", "| 类型 | 时间(ms) | 角色 | 工具 | 拒绝原因 |", "|---|---:|---|---|---|"]
    for x in report['authorizationInterceptions']: lines.append(f"| {x['type']} | {_na(x['elapsedMs'])} | {x['role']} | {x['tool']} | {x['reason']} |")
    lines += ["", "## 时间线", ""] + [f"- #{x['seq']} [{x['eventType']}] {x['summary']}" for x in report['timeline']] + ["", "## 完整性检查", ""]
    lines += [f"- ⚠ {w}" for w in report['integrity']['warnings']] or ["- 通过。"]
    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("session")
    parser.add_argument("--format", choices=("json", "markdown"))
    parser.add_argument("--output")
    args = parser.parse_args()
    try: report = build_report(args.session)
    except AuditLogError as exc: print(f"报告生成失败：{exc}", file=sys.stderr); return 2
    session = Path(args.session)
    outputs = [(Path(args.output), args.format or "json")] if args.output else ([(session / "report.json", "json"), (session / "report.md", "markdown")] if not args.format else [(session / ("report.json" if args.format == "json" else "report.md"), args.format)])
    for path, kind in outputs:
        path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n" if kind == "json" else render_markdown(report), encoding="utf-8")
        print(path)
    return 0


if __name__ == "__main__": raise SystemExit(main())
