#!/usr/bin/env python3
"""评测脚本（Python 标准库，无第三方依赖）。

用法:
  python scripts/evaluate.py <sessionDir> [--cases fixtures/cases.json]
  python scripts/evaluate.py --self-check

读 runs/<session>/findings.json 与标准答案 cases.json，按 Runtime 同款
compute_metrics（review_agent/report.py）输出 命中 / 误报 / 无证据。

自 Step 4 起三数字口径单一来源：`from review_agent.report import compute_metrics`，
scripts/evaluate.py 不再重复实现。
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from review_agent.report import compute_metrics  # noqa: E402

DEFAULT_CASES = REPO_ROOT / "fixtures" / "cases.json"


def _print_metrics(session_dir: str, metrics: dict[str, int]) -> None:
    total = metrics["totalCases"]
    hits = metrics["hits"]
    ratio = f"{(hits / total * 100):.1f}" if total > 0 else "0.0"
    print(f"评测结果  {session_dir}")
    print("--------------------------------")
    print(f"标准答案    {total} 条")
    print(f"命中        {hits}    （{ratio}%）")
    print(f"误报        {metrics['falsePositives']}")
    print(f"无证据      {metrics['noEvidence']}    （应恒为 0）")
    print("--------------------------------")
    if metrics["noEvidence"] != 0:
        print("警告: 存在无证据的 Finding，说明有 Finding 绕过了 evidenceRefs 门卫，请检查。")
    if metrics["falsePositives"] != 0:
        print("警告: 存在误报，说明有 Finding 不在标准答案里，请核对 cases.json 与缺陷行号。")


def evaluate_session(session_dir: Path, cases_path: Path) -> dict[str, int]:
    findings_path = session_dir / "findings.json"
    if not findings_path.is_file():
        raise FileNotFoundError(f"找不到 {findings_path}")
    if not cases_path.is_file():
        raise FileNotFoundError(f"找不到 {cases_path}")

    findings = json.loads(findings_path.read_text(encoding="utf-8"))
    cases = json.loads(cases_path.read_text(encoding="utf-8"))
    if not isinstance(findings, list) or not isinstance(cases, list):
        raise ValueError("findings.json 与 cases.json 都必须是 JSON 数组")
    return compute_metrics(findings, cases)


def self_check() -> int:
    """不依赖一次真实 Run，钉住与 Runtime 相同的三数字规则（含容差 1）。"""
    cases = [
        {"path": "src/server.ts", "startLine": 11},
        {"path": "src/db.ts", "startLine": 5},
    ]
    findings = [
        {
            "path": "src/server.ts",
            "startLine": 12,  # 容差 1，应命中
            "evidenceRefs": ["artifact:abc"],
        },
        {
            "path": "src/db.ts",
            "startLine": 5,
            "evidenceRefs": ["artifact:def"],
        },
        {
            "path": "src/other.ts",
            "startLine": 1,
            "evidenceRefs": [],  # 误报 + 无证据
        },
    ]
    metrics = compute_metrics(findings, cases)
    expected = {"hits": 2, "falsePositives": 1, "noEvidence": 1, "totalCases": 2}
    if metrics != expected:
        print(f"self-check 失败: got {metrics}, expected {expected}", file=sys.stderr)
        return 1
    print("self-check 通过: 命中/误报/无证据规则与 review_agent/report.py 对齐")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="评测 runs/<session> 的命中 / 误报 / 无证据")
    parser.add_argument("session_dir", nargs="?", help="runs/<session> 目录")
    parser.add_argument("--cases", default=str(DEFAULT_CASES), help="标准答案 JSON，默认 fixtures/cases.json")
    parser.add_argument("--self-check", action="store_true", help="运行内置规则自检后退出")
    args = parser.parse_args(argv)

    if args.self_check:
        return self_check()

    if not args.session_dir:
        parser.error("用法: python scripts/evaluate.py <sessionDir> [--cases <cases.json>]")

    try:
        metrics = evaluate_session(Path(args.session_dir), Path(args.cases))
    except (OSError, ValueError, json.JSONDecodeError) as err:
        print(f"评测失败: {err}", file=sys.stderr)
        return 1

    _print_metrics(args.session_dir, metrics)
    return 0 if metrics["totalCases"] > 0 and metrics["hits"] > 0 else 1


if __name__ == "__main__":
    sys.exit(main())
