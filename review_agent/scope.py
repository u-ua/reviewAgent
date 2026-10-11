"""路径权限红线 assert_in_scope（对应 src/scope.ts）。

原则：红线由 Runtime 硬执行，不靠模型自觉。所有只读工具先过这道门。
- 只允许仓库根之内的路径，且必须在 scope 前缀内
- 拒绝路径穿越 `../`、绝对路径逃逸、符号链接逃逸
- 拒绝 `.env` 系敏感文件与 `.git`
- 没有 bash 工具，不改被审仓库
"""

from __future__ import annotations

import os
import re


class ScopeError(Exception):
    pass


def _norm_prefix(p: str) -> str:
    """归一化 scope 前缀：\\ → /，去前导 ./，去尾部 /。"""
    p = p.replace("\\", "/")
    if p.startswith("./"):
        p = p[2:]
    if p.endswith("/"):
        p = p[:-1]
    return p


def is_inside_prefix(rel_path: str, prefix: str) -> bool:
    """判断一个路径（相对仓库根）是否命中某个 scope 前缀目录。"""
    rel = rel_path.replace("\\", "/")
    if rel.startswith("./"):
        rel = rel[2:]
    p = _norm_prefix(prefix)
    return p == "" or rel == p or rel.startswith(p + "/")


def assert_in_scope(repo_root: str, scope_prefixes: list[str], rel_path: str) -> str:
    """校验一个相对仓库根的路径是否在审查范围内。

    通过则返回解析后的绝对路径；否则抛 ScopeError。
    """
    if not isinstance(rel_path, str) or len(rel_path) == 0:
        raise ScopeError("路径不能为空")

    # 归一化：统一分隔符、去掉前导 ./
    normalized = rel_path.replace("\\", "/")
    if normalized.startswith("./"):
        normalized = normalized[2:]
    segments = [s for s in normalized.split("/") if len(s) > 0 and s != "."]

    if len(segments) == 0:
        raise ScopeError("路径不能是仓库根或当前目录")

    # 绝对路径（/ 开头或 Windows 盘符）直接拒绝
    if os.path.isabs(rel_path) or re.match(r"^[a-zA-Z]:[\\/]", rel_path):
        raise ScopeError(f"绝对路径被拒绝: {rel_path}")

    # 路径穿越
    if any(s == ".." for s in segments):
        raise ScopeError(f"路径穿越 ../ 被拒绝: {rel_path}")

    # 敏感文件：.env / .env.local / .git 目录
    if any(s == ".env" or s.startswith(".env.") for s in segments):
        raise ScopeError(f"敏感文件 .env 被拒绝: {rel_path}")
    if any(s == ".git" for s in segments):
        raise ScopeError(f".git 目录被拒绝: {rel_path}")

    # scope 前缀白名单
    in_scope = len(scope_prefixes) == 0 or any(is_inside_prefix(normalized, p) for p in scope_prefixes)
    if not in_scope:
        raise ScopeError(f"路径超出审查范围(scope={','.join(scope_prefixes)}): {rel_path}")

    # realpath 双重校验：符号链接逃逸
    root_real = os.path.realpath(repo_root)
    target_abs = os.path.join(root_real, normalized)
    if not os.path.exists(target_abs):
        raise ScopeError(f"目标不存在: {rel_path}")
    target_real = os.path.realpath(target_abs)

    root_prefix = root_real if root_real.endswith(os.sep) else root_real + os.sep
    if target_real != root_real and not target_real.startswith(root_prefix):
        raise ScopeError(f"符号链接逃逸被拒绝: {rel_path}")

    return target_real
