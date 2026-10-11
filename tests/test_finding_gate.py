"""不变量 3：Finding 写入门卫（对应 tests/finding-gate.test.ts，4 条）。

缺 path/startLine/endLine/evidenceRefs 被拒；evidenceRefs 指向不存在的
artifact 被拒；完整合法的才放行。
"""

from __future__ import annotations

import pytest

from conftest import demo_repo_root, make_ctx
from review_agent.agents import create_executor_tools

REPO = demo_repo_root()


def _valid_finding() -> dict:
    return {
        "id": "finding-1",
        "severity": "high",
        "path": "src/server.ts",
        "startLine": 11,
        "endLine": 11,
        "title": "SQL 注入",
        "rationale": "字符串拼接 SQL",
        "suggestion": "参数化查询",
        "evidenceRefs": ["artifact:abcdef"],
    }


def _finding_write_tool():
    return next(t for t in create_executor_tools() if t.name == "finding_write")


def test_不变量3_缺必填字段的_Finding_被拒():
    ctx = make_ctx(repo_root=REPO, scope=["src"])
    tool = _finding_write_tool()

    # 先生成一个真实证据，让"缺字段"是唯一被拒理由
    artifact = ctx.stores.artifactStore.write(
        task_id="task:x", kind="code", media_type="text/plain", content="line 11",
        source_path="src/server.ts", source_start_line=11, source_end_line=11,
    )
    base = _valid_finding()
    base["evidenceRefs"] = [artifact.artifactRef]

    cases = [
        ("缺 path", lambda f: f.pop("path")),
        ("缺 startLine", lambda f: f.pop("startLine")),
        ("缺 endLine", lambda f: f.pop("endLine")),
        ("startLine 非整数", lambda f: f.update(startLine=1.5)),
        ("endLine < startLine", lambda f: f.update(endLine=3)),
        ("缺 evidenceRefs", lambda f: f.update(evidenceRefs=[])),
        ("severity 非法", lambda f: f.update(severity="fatal")),
    ]
    for label, mutate in cases:
        args = dict(base)
        mutate(args)
        result = tool.execute(args, ctx)
        assert result["ok"] is False, f"应拒绝: {label}"
        assert result["summary"].startswith("Finding 被拒绝"), f"{label}: {result['summary']}"


def test_不变量3_evidenceRefs指向不存在的_artifact_被拒():
    ctx = make_ctx(repo_root=REPO, scope=["src"])
    tool = _finding_write_tool()
    args = _valid_finding()
    args["evidenceRefs"] = ["artifact:does-not-exist"]
    result = tool.execute(args, ctx)
    assert result["ok"] is False
    assert "证据引用不存在" in result.get("error", "")


def test_不变量3_scope外路径的_Finding_被拒():
    ctx = make_ctx(repo_root=REPO, scope=["src"])
    tool = _finding_write_tool()
    args = _valid_finding()
    args["path"] = "../secret.txt"
    result = tool.execute(args, ctx)
    assert result["ok"] is False


def test_不变量3补_完整合法的_Finding_放行并入库():
    ctx = make_ctx(repo_root=REPO, scope=["src"], task_id="task:x")
    tool = _finding_write_tool()
    artifact = ctx.stores.artifactStore.write(
        task_id="task:x",
        kind="code",
        media_type="text/plain",
        content='const sql = "..." + x',
        source_path="src/server.ts",
        source_start_line=11,
        source_end_line=11,
    )

    args = _valid_finding()
    args["evidenceRefs"] = [artifact.artifactRef]
    result = tool.execute(args, ctx)
    assert result["ok"] is True, result.get("error", "")
    assert result["ok"] is True

    stored = ctx.stores.findingStore.list()
    assert len(stored) == 1
    f = stored[0]
    assert f.path == "src/server.ts"
    assert f.taskId == "task:x"


def test_不变量3补_行号超出代码证据范围的_Finding_被拒():
    ctx = make_ctx(repo_root=REPO, scope=["src"], task_id="task:x")
    code = ctx.stores.artifactStore.write(
        task_id="task:x", kind="code", media_type="text/plain", content="line 11",
        source_path="src/server.ts", source_start_line=11, source_end_line=11,
    )
    args = _valid_finding()
    args["startLine"] = 12
    args["endLine"] = 12
    args["evidenceRefs"] = [code.artifactRef]

    result = _finding_write_tool().execute(args, ctx)

    assert result["ok"] is False
    assert result["rejectionReason"] == "line_outside_evidence"


def test_不变量3补_代码证据覆盖行号的_Finding_放行():
    ctx = make_ctx(repo_root=REPO, scope=["src"], task_id="task:x")
    code = ctx.stores.artifactStore.write(
        task_id="task:x", kind="code", media_type="text/plain", content="line 10\nline 11\nline 12",
        source_path="src/server.ts", source_start_line=10, source_end_line=12,
    )
    args = _valid_finding()
    args["evidenceRefs"] = [code.artifactRef]

    result = _finding_write_tool().execute(args, ctx)

    assert result["ok"] is True, result.get("error", "")


def test_RAG模式_缺规则证据的_Finding_被拒():
    ctx = make_ctx(repo_root=REPO, scope=["src"], task_id="task:x")
    ctx.stores.ragStore = object()
    code = ctx.stores.artifactStore.write(
        task_id="task:x", kind="code", media_type="text/plain", content="SQL source",
        source_path="src/server.ts", source_start_line=11, source_end_line=11,
    )
    args = _valid_finding()
    args["evidenceRefs"] = [code.artifactRef]
    result = _finding_write_tool().execute(args, ctx)
    assert result["ok"] is False
    assert "ruleEvidenceRefs 不能为空" in result["error"]


def test_RAG模式_两类证据类型不能混用():
    ctx = make_ctx(repo_root=REPO, scope=["src"], task_id="task:x")
    ctx.stores.ragStore = object()
    code = ctx.stores.artifactStore.write(
        task_id="task:x", kind="code", media_type="text/plain", content="SQL source",
        source_path="src/server.ts", source_start_line=11, source_end_line=11,
    )
    args = _valid_finding()
    args["evidenceRefs"] = [code.artifactRef]
    args["ruleEvidenceRefs"] = [code.artifactRef]
    result = _finding_write_tool().execute(args, ctx)
    assert result["ok"] is False
    assert "规则证据类型非法" in result["error"]


def test_RAG模式_源码和规则证据齐全才放行():
    ctx = make_ctx(repo_root=REPO, scope=["src"], task_id="task:x")
    ctx.stores.ragStore = object()
    code = ctx.stores.artifactStore.write(
        task_id="task:x", kind="code", media_type="text/plain", content="SQL source",
        source_path="src/server.ts", source_start_line=11, source_end_line=11,
    )
    rule = ctx.stores.artifactStore.write(
        task_id="task:x", kind="rule", media_type="application/json", content='{"ruleId":"CWE-89"}'
    )
    args = _valid_finding()
    args["evidenceRefs"] = [code.artifactRef]
    args["ruleEvidenceRefs"] = [rule.artifactRef]
    result = _finding_write_tool().execute(args, ctx)
    assert result["ok"] is True
    finding = ctx.stores.findingStore.list()[0]
    assert finding.evidenceRefs == [code.artifactRef]
    assert finding.ruleEvidenceRefs == [rule.artifactRef]


@pytest.mark.parametrize("dimension", ["performance", "logic"])
def test_非安全维度在RAG模式仅有源码证据也能提交(dimension):
    ctx = make_ctx(repo_root=REPO, scope=["src"], task_id="task:x", task_dimension=dimension)
    ctx.stores.ragStore = object()
    code = ctx.stores.artifactStore.write(
        task_id="task:x", kind="code", media_type="text/plain", content="source",
        source_path="src/server.ts", source_start_line=11, source_end_line=11,
    )
    args = _valid_finding()
    args["evidenceRefs"] = [code.artifactRef]
    result = _finding_write_tool().execute(args, ctx)
    assert result["ok"] is True
    assert ctx.stores.findingStore.list()[0].dimension == dimension


def test_Executor不能跨维度提交Finding():
    ctx = make_ctx(repo_root=REPO, scope=["src"], task_id="task:x", task_dimension="logic")
    code = ctx.stores.artifactStore.write(
        task_id="task:x", kind="code", media_type="text/plain", content="source",
        source_path="src/server.ts", source_start_line=11, source_end_line=11,
    )
    args = _valid_finding()
    args["evidenceRefs"] = [code.artifactRef]
    args["dimension"] = "security"
    result = _finding_write_tool().execute(args, ctx)
    assert result["ok"] is False
    assert "不一致" in result["error"]
