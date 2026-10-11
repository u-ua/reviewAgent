"""从 execution.jsonl 重建运行指标；不写入第二套审计日志。"""
from __future__ import annotations

import json
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

ACCESS_REASONS = ("path_traversal", "outside_scope", "sensitive_path", "symlink_escape", "role_tool_denied", "absolute_path")


def read_events(path: str | Path) -> list[dict[str, Any]]:
    """容忍旧事件和损坏行，保留能识别的字段以生成部分指标。"""
    events = []
    try:
        lines = Path(path).read_text(encoding="utf-8").splitlines()
    except OSError:
        return events
    for line in lines:
        try:
            item = json.loads(line)
            if isinstance(item, dict):
                events.append(item)
        except json.JSONDecodeError:
            continue
    return events


def _mean(values: list[int]) -> float | None:
    return round(sum(values) / len(values), 3) if values else None


def _usage(payload: dict) -> tuple[int | None, int | None, int | None]:
    u = payload.get("usage")
    if not isinstance(u, dict): return None, None, None
    def n(key):
        value = u.get(key)
        return value if isinstance(value, int) and value >= 0 else None
    return n("promptTokens"), n("completionTokens"), n("totalTokens")


def build_metrics(events: list[dict[str, Any]], pricing: dict[str, dict[str, float]] | None = None) -> dict[str, Any]:
    """纯投影函数。pricing 的单位为每 1K tokens 的 input/output 成本。"""
    pricing = pricing or {}
    accepted = [e for e in events if e.get("eventType") == "finding_accepted"]
    rejected = [e for e in events if e.get("eventType") == "finding_rejected"]
    by_dimension, by_severity, by_file = Counter(), Counter(), Counter()
    for e in accepted:
        args = (e.get("payload") or {}).get("args") or {}
        dimension = args.get("dimension") or (e.get("payload") or {}).get("dimension") or "unknown"
        by_dimension[dimension] += 1
        by_severity[args.get("severity") or "unknown"] += 1
        by_file[args.get("path") or "unknown"] += 1
    rejection_reasons = Counter((e.get("payload") or {}).get("rejectionReason") or "unknown" for e in rejected)

    decisions = [e for e in events if e.get("eventType") == "tool_access_decision"]
    access_by_reason = {reason: {"attempts": 0, "blocked": 0, "rate": None} for reason in ACCESS_REASONS}
    # 只用显式 decision 作为分母；旧 tool_access_blocked 只能证明一次阻止，不能证明尝试总数。
    for e in decisions:
        payload = e.get("payload") or {}
        reason = payload.get("reason")
        if reason in access_by_reason and payload.get("allowed") is False:
            access_by_reason[reason]["attempts"] += 1
            if payload.get("blocked") is True: access_by_reason[reason]["blocked"] += 1
    for item in access_by_reason.values():
        item["rate"] = item["blocked"] / item["attempts"] if item["attempts"] else None
    attempts = sum(x["attempts"] for x in access_by_reason.values())
    blocked_count = sum(x["blocked"] for x in access_by_reason.values())

    starts, task_durations = {}, defaultdict(list)
    for e in events:
        task_id, elapsed = e.get("taskId"), e.get("elapsedMs")
        if not task_id or not isinstance(elapsed, int): continue
        if e.get("eventType") == "task_started": starts[(task_id, e.get("epochId"))] = elapsed
        if e.get("eventType") == "task_finished":
            start = starts.get((task_id, e.get("epochId")))
            if start is not None:
                dim = (e.get("payload") or {}).get("dimension", "unknown")
                task_durations[dim].append(max(0, elapsed - start))
    all_task_durations = [x for xs in task_durations.values() for x in xs]
    elapsed_values = [e.get("elapsedMs") for e in events if isinstance(e.get("elapsedMs"), int)]
    llm_events = [e for e in events if e.get("eventType") == "llm_call"]
    llm_durations = [(e.get("payload") or {}).get("durationMs") for e in llm_events]
    tool_durations = [(e.get("payload") or {}).get("durationMs") for e in events if e.get("eventType") in ("tool_call", "submit", "finding_accepted", "finding_rejected")]

    token_rows, prompt_total, completion_total, total_total = [], 0, 0, 0
    successful_llm_calls = 0
    available_fields = {"promptTokens": 0, "completionTokens": 0, "totalTokens": 0}
    # 没有成功调用时没有成本事实；绝不能把初始累加值 0.0 当成真实成本。
    cost_total: float | None = None
    for e in llm_events:
        p = e.get("payload") or {}
        if not p.get("success"): continue  # 失败响应不计入，避免重试重复
        successful_llm_calls += 1
        if successful_llm_calls == 1:
            cost_total = 0.0
        prompt, completion, total = _usage(p)
        model = p.get("model")
        row = {"model": model, "role": e.get("role"), "promptTokens": prompt, "completionTokens": completion, "totalTokens": total, "synthetic": bool(p.get("synthetic")), "cost": None}
        if prompt is not None: prompt_total += prompt; available_fields["promptTokens"] += 1
        if completion is not None: completion_total += completion; available_fields["completionTokens"] += 1
        if total is not None: total_total += total; available_fields["totalTokens"] += 1
        price = pricing.get(model) if isinstance(model, str) else None
        if prompt is not None and completion is not None and isinstance(price, dict) and isinstance(price.get("inputPer1K"), (int,float)) and isinstance(price.get("outputPer1K"), (int,float)):
            row["cost"] = round(prompt / 1000 * price["inputPer1K"] + completion / 1000 * price["outputPer1K"], 8)
            if cost_total is not None: cost_total += row["cost"]
        else:
            cost_total = None
        token_rows.append(row)
    return {
        "schemaVersion": 1,
        "findings": {"total": len(accepted), "byDimension": dict(by_dimension), "bySeverity": dict(by_severity), "byFile": dict(by_file)},
        "evidenceValidity": {"attempts": len(accepted)+len(rejected), "accepted": len(accepted), "rejected": len(rejected), "rate": len(accepted)/(len(accepted)+len(rejected)) if accepted or rejected else None, "rejectedByReason": dict(rejection_reasons)},
        "authorizationInterception": {"attempts": attempts, "blocked": blocked_count, "rate": blocked_count/attempts if attempts else None, "byReason": access_by_reason},
        "durationsMs": {"session": max(elapsed_values)-min(elapsed_values) if len(elapsed_values) >= 2 else None, "averageTask": _mean(all_task_durations), "byDimensionAverageTask": {k:_mean(v) for k,v in task_durations.items()}, "llmCalls": [x for x in llm_durations if isinstance(x,int)], "averageLlmCall": _mean([x for x in llm_durations if isinstance(x,int)]), "toolCalls": [x for x in tool_durations if isinstance(x,int)], "averageToolCall": _mean([x for x in tool_durations if isinstance(x,int)])},
        "tokens": {
            # 部分响应缺 usage 时保留已知精确和，并明确标为 partial；全缺时绝不把 0 当用量。
            "promptTokens": prompt_total if available_fields["promptTokens"] else None,
            "completionTokens": completion_total if available_fields["completionTokens"] else None,
            "totalTokens": total_total if available_fields["totalTokens"] else None,
            "status": ("no_successful_calls" if not successful_llm_calls else "complete" if all(v == successful_llm_calls for v in available_fields.values()) else "partial" if any(available_fields.values()) else "unavailable"),
            "successfulCalls": successful_llm_calls,
            "usageAvailableCalls": available_fields,
            "calls": token_rows,
        },
        "cost": {"currency": "configured", "total": round(cost_total, 8) if cost_total is not None else None, "pricingConfigured": bool(pricing)},
    }


def write_metrics(session_dir: str | Path, pricing: dict[str, dict[str, float]] | None = None) -> dict[str, Any]:
    session = Path(session_dir)
    metrics = build_metrics(read_events(session / "execution.jsonl"), pricing)
    (session / "metrics.json").write_text(json.dumps(metrics, ensure_ascii=False, indent=2), encoding="utf-8")
    return metrics
