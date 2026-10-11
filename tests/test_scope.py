"""不变量 2：越界读取失败（对应 tests/scope.test.ts，4 条）。

../ 路径穿越、.env、.git、scope 外、绝对路径全被拒。
只读工具一律先过 assert_in_scope 权限门。
"""

from __future__ import annotations

import pytest

from conftest import demo_repo_root, make_ctx
from review_agent.agents import create_executor_tools
from review_agent.scope import ScopeError, assert_in_scope

REPO = demo_repo_root()
SCOPE = ["src"]


def test_不变量2_越界路径全部被拒():
    for bad in [
        "../secret.txt",
        "src/../../package.json",
        "src/.env",
        "src/.env.local",
        ".git/config",
        "src/.git/config",
        "other/file.ts",
        "C:/Windows/win.ini",
        "D:/secret.txt",
        "",
    ]:
        with pytest.raises(ScopeError):
            assert_in_scope(REPO, SCOPE, bad)


def test_不变量2_scope内合法路径放行并解析到真实绝对路径():
    abs_path = assert_in_scope(REPO, SCOPE, "src/server.ts")
    assert abs_path.replace("\\", "/").endswith("fixtures/demo-repo/src/server.ts")


def test_不变量2_read_file工具对越界路径返回失败():
    tools = create_executor_tools()
    read_file = next(t for t in tools if t.name == "read_file")
    ctx = make_ctx(repo_root=REPO, scope=SCOPE)

    ok_result = read_file.execute({"path": "src/server.ts"}, ctx)
    assert ok_result["ok"] is True

    for bad in ["../secret.txt", "src/.env", "other/file.ts"]:
        result = read_file.execute({"path": bad}, ctx)
        assert result["ok"] is False, f"read_file 应拒绝: {bad}"
        error = result.get("error", "")
        assert any(k in error for k in ("ScopeError", "拒绝", "超出")), f"{bad}: {error}"


def test_不变量2补_空scope等于整个仓库():
    tools = create_executor_tools()
    read_file = next(t for t in tools if t.name == "read_file")
    ctx = make_ctx(repo_root=REPO, scope=[])
    result = read_file.execute({"path": "src/db.ts"}, ctx)
    assert result["ok"] is True
    assert result.get("artifactRef"), "read_file 应产出 artifactRef 证据"
