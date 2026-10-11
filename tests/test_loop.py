"""端到端：完整跑一次 demo-repo（fake provider）（对应 loop.test.ts，2 条）。

产物齐全（execution.jsonl / tasks.json / findings.json / review.md / artifacts/），
且 8 个预埋缺陷全命中、零误报、零无证据；账本 append-only。
"""

from __future__ import annotations

import json
from pathlib import Path

from conftest import demo_repo_root, make_session_dir
from review_agent.controller import ReviewController
from review_agent.providers.fake import FakeAgentProvider

REPO = demo_repo_root()
CASES = json.loads(
    (Path(__file__).resolve().parent.parent / "fixtures" / "cases.json").read_text(encoding="utf-8")
)


def _config(goal: str = "审查演示仓库的代码质量与安全问题"):
    return {"repoRoot": REPO, "scope": ["src"], "goal": goal, "maxCycles": 6, "provider": "fake"}


def test_端到端_演示仓库8缺陷全命中_零误报_零无证据():
    session_dir = make_session_dir()
    controller = ReviewController(_config(), FakeAgentProvider(), session_dir=session_dir, cases=CASES)
    result = controller.run_until_done()

    # 三数字
    assert result.metrics["hits"] == 8, "应命中全部 8 条标准答案"
    assert result.metrics["falsePositives"] == 0
    assert result.metrics["noEvidence"] == 0
    assert controller.goalState["status"] == "completed"

    # 档案室产物齐全
    for file in ["execution.jsonl", "tasks.json", "findings.json", "review.md"]:
        assert Path(session_dir, file).exists(), f"缺少 {file}"
    artifact_files = list(Path(session_dir, "artifacts").iterdir())
    assert len(artifact_files) > 0, "artifacts/ 应有证据文件"

    # 每条 Finding 都必须带证据引用，且引用能对到 artifacts/ 里的真实文件
    assert len(result.findings) == 8
    for f in result.findings:
        assert len(f.evidenceRefs) > 0, f"{f.id} 缺证据"
        assert f.path and f.startLine >= 1 and f.endLine >= f.startLine, f"{f.id} 行号非法"

    # 报告里能读到评测数字与证据摘录
    report = Path(result.reportPath).read_text(encoding="utf-8")
    assert "命中 8 / 误报 0 / 无证据 0" in report
    assert "证据" in report
    assert result.reportPath.endswith("review.md")


def test_端到端_execution_jsonl是append_only且含每次工具调用():
    session_dir = make_session_dir()
    controller = ReviewController(
        _config(goal="审查演示仓库"), FakeAgentProvider(), session_dir=session_dir
    )
    controller.run_until_done()

    raw = Path(session_dir, "execution.jsonl").read_text(encoding="utf-8")
    lines = [l for l in raw.split("\n") if l.strip()]
    assert len(lines) > 20, f"账本应有足够事件，实际 {len(lines)}"
    first = json.loads(lines[0])
    last = json.loads(lines[-1])
    assert first["id"] == "event:1"
    assert last["seq"] == len(lines)
