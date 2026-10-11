import json

import pytest

from scripts.generate_report import AuditLogError, build_report, render_markdown


def event(seq, kind, **extra):
    return {"id": f"event:{seq}", "seq": seq, "role": "runtime", "eventType": kind,
            "summary": kind, "artifactRefs": [], "elapsedMs": seq * 10, **extra}


def write_session(tmp_path, events, tasks=None, findings=None):
    session = tmp_path / "runs" / "windows-session"
    session.mkdir(parents=True)
    session.joinpath("execution.jsonl").write_text("\n".join(json.dumps(x) for x in events) + "\n", encoding="utf-8")
    if tasks is not None: session.joinpath("tasks.json").write_text(json.dumps(tasks), encoding="utf-8")
    if findings is not None: session.joinpath("findings.json").write_text(json.dumps(findings), encoding="utf-8")
    return session


def test_complete_session_and_markdown_dimensions(tmp_path):
    events = [event(1, "run_started", summary="审查目标：demo", payload={"scope": ["src"]}),
              event(2, "task_started", taskId="task:security", epochId="e", payload={"dimension": "security"}),
              event(3, "finding_accepted", taskId="task:security", payload={"args": {"id": "f1", "dimension": "security", "severity": "high", "path": "src/a.py", "startLine": 2}}),
              event(4, "task_finished", taskId="task:security", epochId="e", payload={"dimension": "security"}), event(5, "run_finished")]
    report = build_report(write_session(tmp_path, events, [{"taskId": "task:security", "dimension": "security", "goal": "g", "status": "completed"}], [{"id": "f1", "dimension": "security", "severity": "high", "path": "src/a.py", "startLine": 2, "evidenceRefs": []}]))
    assert report["metrics"]["findings"]["total"] == 1
    markdown = render_markdown(report)
    assert all(f"Findings — {x}" in markdown for x in ("security", "performance", "logic"))
    assert "关键指标" in markdown


def test_empty_findings_and_na_metrics(tmp_path):
    report = build_report(write_session(tmp_path, [event(1, "run_started")], [], []))
    assert report["findings"]["security"] == []
    assert "N/A" in render_markdown(report)


def test_legacy_findings_fallback_unknown_dimension_and_duplicates(tmp_path):
    findings = [
        {"id": "old", "severity": "high", "path": "src/a.py", "startLine": 3, "title": "历史问题"},
        {"id": "old", "severity": "low", "path": "src/b.py", "startLine": 4, "title": "重复历史问题"},
    ]
    report = build_report(write_session(tmp_path, [event(1, "run_started")], [], findings))
    assert len(report["findings"]["unknown"]) == 2
    warnings = "\n".join(report["integrity"]["warnings"])
    assert "legacy fallback" in warnings and "findings.json 中重复 Finding ID" in warnings
    assert "Findings — unknown" in render_markdown(report)


def test_no_llm_calls_markdown_renders_cost_na(tmp_path):
    report = build_report(write_session(tmp_path, [event(1, "run_started")], [], []))
    assert report["metrics"]["cost"]["total"] is None
    assert "| 0 | N/A | N/A | N/A ms | 0 | N/A | N/A |" in render_markdown(report)


def test_missing_artifact_and_seq_gap_warn(tmp_path):
    events = [event(1, "run_started"), event(3, "finding_accepted", payload={"args": {"id": "f", "dimension": "logic", "evidenceRefs": ["artifact:" + "a" * 64]}})]
    report = build_report(write_session(tmp_path, events, [], [{"id": "f", "dimension": "logic", "evidenceRefs": ["artifact:" + "a" * 64]}]))
    warnings = "\n".join(report["integrity"]["warnings"])
    assert "seq 不连续" in warnings and "Artifact 不存在" in warnings


def test_malformed_jsonl_fails_clearly(tmp_path):
    session = tmp_path / "broken"; session.mkdir()
    session.joinpath("execution.jsonl").write_text("{bad}\n", encoding="utf-8")
    with pytest.raises(AuditLogError, match="第 1 行 JSON 损坏"):
        build_report(session)


def test_generator_is_read_only_for_source_artifacts(tmp_path):
    session = write_session(tmp_path, [event(1, "run_started")], [], [])
    original = session.joinpath("execution.jsonl").read_bytes()
    build_report(session)
    assert session.joinpath("execution.jsonl").read_bytes() == original
