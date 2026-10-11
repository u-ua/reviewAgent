"""只读工具：list_files / read_file / grep / git_diff（对应 src/tools/read-only-tools.ts）。

全部先过 assert_in_scope 权限门；没有 bash；不改被审仓库。
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

from ..scope import assert_in_scope, is_inside_prefix
from ..types import Tool, ToolParam

MAX_READ_LINES = 400
MAX_LIST_ENTRIES = 500
MAX_GREP_MATCHES = 200
MAX_DIFF_BYTES = 100_000

# 排除目录：版本库、敏感文件、依赖产物
EXCLUDED_DIR = {".git", "node_modules", "dist", "build", "out"}
EXCLUDED_FILE = {".env"}


# ---------------------------------------------------------------------------
# 受 scope 约束的文件遍历
# ---------------------------------------------------------------------------

def is_in_scope(scope: list[str], rel_path: str) -> bool:
    if len(scope) == 0:
        return True
    return any(is_inside_prefix(rel_path, p) for p in scope)


def _is_binary(head: bytes) -> bool:
    return b"\x00" in head


def _safe_read_head(abs_path: str) -> bytes:
    try:
        size = min(os.path.getsize(abs_path), 1024)
        with open(abs_path, "rb") as f:
            return f.read(size)
    except OSError:
        return b""


def collect_files(
    repo_root: str,
    scope: list[str],
    from_rel: str = ".",
    max_entries: int = MAX_LIST_ENTRIES,
) -> list[str]:
    """收集范围内（默认从仓库根）的普通文本文件相对路径。"""
    root_real = os.path.realpath(repo_root)
    from_norm = from_rel.replace("\\", "/")
    if from_norm.startswith("./"):
        from_norm = from_norm[2:]
    if from_norm and from_norm != "." and not is_in_scope(scope, from_norm):
        raise ValueError(f"起始目录超出审查范围: {from_rel}")
    base_abs = os.path.join(root_real, from_norm) if from_norm and from_norm != "." else root_real

    results: list[str] = []

    def walk(dir_abs: str) -> None:
        if len(results) >= max_entries:
            return
        try:
            entries = sorted(os.scandir(dir_abs), key=lambda e: e.name)
        except OSError:
            return
        for entry in entries:
            if len(results) >= max_entries:
                return
            name = entry.name
            if entry.is_dir(follow_symlinks=False):
                if name in EXCLUDED_DIR or name.startswith(".env"):
                    continue
                walk(entry.path)
            elif entry.is_file(follow_symlinks=False):
                if name in EXCLUDED_FILE or name.startswith(".env"):
                    continue
                rel = os.path.relpath(entry.path, root_real).replace("\\", "/")
                if not is_in_scope(scope, rel):
                    continue
                if _is_binary(_safe_read_head(entry.path)):
                    continue
                results.append(rel)

    walk(base_abs)
    return results


def _err(err_value: Exception) -> dict:
    message = str(err_value)
    return {"ok": False, "summary": f"工具调用失败: {message}", "error": message}


# ---------------------------------------------------------------------------
# list_files
# ---------------------------------------------------------------------------

def _list_files_execute(args, ctx) -> dict:
    rel = args.get("path", ".")
    files = collect_files(ctx.repoRoot, ctx.scope, rel)
    capped = files[:MAX_LIST_ENTRIES]
    if len(capped) == 0:
        text = "(空)"
    else:
        text = "\n".join(capped)
        if len(files) > len(capped):
            text += f"\n... 还有 {len(files) - len(capped)} 个文件未列出"
    return {"ok": True, "summary": f"列出 {len(capped)} 个文件", "text": text}


def _build_list_files_tool() -> Tool:
    return Tool(
        name="list_files",
        description="列出审查范围内的文件。目录相对仓库根，默认从整个 scope 开始。",
        parameters=[
            ToolParam("path", "string", "起始目录（相对仓库根），默认 \".\"", False),
            ToolParam("recursive", "boolean", "是否递归列出子目录文件，默认 true", False),
        ],
        execute=_list_files_execute,
    )


# ---------------------------------------------------------------------------
# read_file
# ---------------------------------------------------------------------------

def _read_file_execute(args, ctx) -> dict:
    rel_path = args.get("path")
    try:
        abs_path = assert_in_scope(ctx.repoRoot, ctx.scope, rel_path)
    except Exception as e:
        return _err(e)
    if not os.path.isfile(abs_path):
        return _err(ValueError(f"文件不存在: {rel_path}"))

    try:
        content = Path(abs_path).read_text(encoding="utf-8")
    except OSError as e:
        return _err(e)

    all_lines = content.split("\n")
    total = len(all_lines)
    start_val = args.get("startLine", 1)
    end_val = args.get("endLine", total)
    start = max(1, int(float(start_val if start_val is not None else 1)))
    end = min(total, int(float(end_val if end_val is not None else total)))
    if start > end:
        return _err(ValueError(f"startLine({start}) 大于 endLine({end})"))

    # 上限截断
    truncated = end - start + 1 > MAX_READ_LINES
    if truncated:
        end = start + MAX_READ_LINES - 1

    slice_lines = all_lines[start - 1 : end]
    numbered = "\n".join(f"{start + i}: {line}" for i, line in enumerate(slice_lines))
    raw_slice = "\n".join(slice_lines)

    artifact = ctx.stores.artifactStore.write(
        task_id=ctx.taskId or "run",
        kind="code",
        media_type="text/plain",
        content=raw_slice,
        source_path=rel_path,
        source_start_line=start,
        source_end_line=end,
    )

    note = f"\n...(第 {end} 行后截断，如需更多请缩小范围)" if truncated else ""
    return {
        "ok": True,
        "summary": f"读取 {rel_path} 第 {start}-{end} 行（共 {total} 行）",
        "text": numbered + note,
        "artifactRef": artifact.artifactRef,
    }


def _build_read_file_tool() -> Tool:
    return Tool(
        name="read_file",
        description=(
            "读取范围内文件。返回带行号的文本，并把读到的代码片段存成 Artifact"
            " 供 Finding 引用。超过上限的行段会被截断。"
        ),
        parameters=[
            ToolParam("path", "string", "相对仓库根的文件路径", True),
            ToolParam("startLine", "number", "起始行（1 起），默认 1", False),
            ToolParam("endLine", "number", "结束行（含），默认读到底", False),
        ],
        execute=_read_file_execute,
    )


# ---------------------------------------------------------------------------
# grep
# ---------------------------------------------------------------------------

def _grep_execute(args, ctx) -> dict:
    pattern = args.get("pattern")
    try:
        import re as _re

        _re.compile(pattern)
    except Exception as e:
        return _err(ValueError(f"非法正则: {e}"))
    from_rel = args.get("path", ".")
    try:
        files = collect_files(ctx.repoRoot, ctx.scope, from_rel)
    except Exception as e:
        return _err(e)

    import re as _re

    regex = _re.compile(pattern, _re.IGNORECASE)
    matches: list[str] = []
    for rel in files:
        if len(matches) >= MAX_GREP_MATCHES:
            break
        try:
            lines = Path(ctx.repoRoot, rel).read_text(encoding="utf-8").split("\n")
        except OSError:
            continue
        for i, line in enumerate(lines):
            if len(matches) >= MAX_GREP_MATCHES:
                break
            if line is None:
                continue
            if regex.search(line):
                matches.append(f"{rel}:{i + 1}: {line.rstrip()}")

    if len(matches) == 0:
        return {"ok": True, "summary": f"无匹配: /{pattern}/", "text": "(无匹配)"}
    text = "\n".join(matches)
    if len(matches) >= MAX_GREP_MATCHES:
        text += f"\n...(达到上限 {MAX_GREP_MATCHES})"
    return {"ok": True, "summary": f"匹配 {len(matches)} 处", "text": text}


def _build_grep_tool() -> Tool:
    return Tool(
        name="grep",
        description="在范围内按正则搜索（大小写不敏感），返回 文件:行号: 内容。",
        parameters=[
            ToolParam("pattern", "string", "正则表达式", True),
            ToolParam("path", "string", "限定目录（相对仓库根），默认整个 scope", False),
        ],
        execute=_grep_execute,
    )


# ---------------------------------------------------------------------------
# git_diff
# ---------------------------------------------------------------------------

def _git_fallback() -> dict:
    return {
        "ok": True,
        "summary": "git 不可用或不是 git 仓库，退回用 read_file/list_files 直接审查",
        "text": "(git diff 不可用)",
    }


def _git_diff_execute(args, ctx) -> dict:
    base = args.get("base") or "HEAD"
    try:
        completed = subprocess.run(
            ["git", "-C", ctx.repoRoot, "diff", base, "--"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=30,
        )
        stdout = completed.stdout
        if completed.returncode != 0:
            return _git_fallback()
    except Exception:
        return _git_fallback()

    if len(stdout) == 0:
        return {"ok": True, "summary": f"相对 {base} 无改动（或工作区干净）", "text": "(空 diff)"}

    bounded = stdout[:MAX_DIFF_BYTES]
    artifact = ctx.stores.artifactStore.write(
        task_id=ctx.taskId or "run",
        kind="diff",
        media_type="text/x-diff",
        content=bounded,
    )
    return {
        "ok": True,
        "summary": f"相对 {base} 的 diff 已存为证据",
        "text": bounded[:4000] + ("\n...(已截断，详见 Artifact)" if len(bounded) > 4000 else ""),
        "artifactRef": artifact.artifactRef,
    }


def _build_git_diff_tool() -> Tool:
    return Tool(
        name="git_diff",
        description="查看相对 base 分支/commit 的改动。无 git 或失败时退回提示读文件。",
        parameters=[
            ToolParam("base", "string", "基准分支或 commit；不填用 HEAD", False),
        ],
        execute=_git_diff_execute,
    )


# ---------------------------------------------------------------------------
# 工具箱
# ---------------------------------------------------------------------------

def create_read_only_tools() -> list[Tool]:
    return [_build_list_files_tool(), _build_read_file_tool(), _build_grep_tool(), _build_git_diff_tool()]
