"""命令行入口（对应 src/cli.ts，参数逐一对齐）。

  python -m review_agent --repo fixtures/demo-repo --scope src \
      --goal "审查演示仓库的代码质量与安全问题" --provider fake --max-cycles 6

可选 --base（git 基准 commit/分支）、--json（输出 JSON）、--help。
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from .controller import ReviewController
from .providers.fake import FakeAgentProvider
from .providers.openai import OpenAiAgentProvider, load_openai_config_from_env
from .rag.config import load_rag_config
from .rag.embeddings import DashScopeEmbeddingClient
from .rag.store import QdrantRuleStore
from qdrant_client import QdrantClient

HELP_TEXT = """review-agent — 证据驱动的多 Agent 代码审查 Runtime

用法:
  python -m review_agent --repo <路径> [选项]

必填:
  --repo <路径>         被审仓库（绝对或相对路径）
  --goal <文本>         审查目标（必须能判定对错）

选项:
  --scope <a,b,...>     审查范围（相对仓库根的目录前缀），缺省=整个仓库
  --base <ref>          git 基准 commit/分支（供 git_diff），可选
  --max-cycles <n>      Planner 最大循环数，默认 6
  --max-concurrent-executors <n>  同一批无依赖 Executor 上限，默认 2
  --provider <fake|openai>  默认 fake（离线确定性）；openai 需 .env 配置
  --rag                 为 Executor 启用受控规则知识库检索
  --cases <json>        L0 标准答案文件，评测命中/误报/无证据
  --json                输出运行摘要为 JSON
  --help                显示本帮助"""


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m review_agent",
        add_help=False,  # 自定义 --help，输出与 cli.ts 一致
    )
    parser.add_argument("--repo")
    parser.add_argument("--goal")
    parser.add_argument("--scope", help="逗号分隔的目录前缀，如 src,tests")
    parser.add_argument("--base")
    parser.add_argument("--max-cycles", type=int, default=6)
    parser.add_argument("--max-concurrent-executors", type=int, default=2)
    parser.add_argument("--provider", choices=("fake", "openai"), default="fake")
    parser.add_argument("--rag", action="store_true")
    parser.add_argument("--cases")
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--help", action="store_true")
    return parser


def load_cases(cases_path: str | None) -> list | None:
    if not cases_path:
        return None
    raw = json.loads(Path(cases_path).read_text(encoding="utf-8"))
    if not isinstance(raw, list):
        raise ValueError("--cases 必须是 JSON 数组")
    return raw


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    if args.help:
        print(HELP_TEXT)
        return 0
    if not args.repo:
        print("缺少 --repo（用 --help 查看用法）", file=sys.stderr)
        return 2
    if not args.goal:
        print("缺少 --goal（用 --help 查看用法）", file=sys.stderr)
        return 2
    if args.max_concurrent_executors < 1:
        print("--max-concurrent-executors 必须至少为 1", file=sys.stderr)
        return 2

    scope = [s.strip() for s in args.scope.split(",") if s.strip()] if args.scope else []
    cases = None
    try:
        cases = load_cases(args.cases)
    except (OSError, ValueError, json.JSONDecodeError) as err:
        print(f"参数错误: --cases {err}", file=sys.stderr)
        return 2

    try:
        repo_root = os.path.abspath(args.repo)
        provider = (
            OpenAiAgentProvider(load_openai_config_from_env())
            if args.provider == "openai"
            else FakeAgentProvider()
        )
        config = {
            "repoRoot": repo_root,
            "scope": scope,
            "goal": args.goal,
            "base": args.base,
            "maxCycles": args.max_cycles,
            "maxConcurrentExecutors": args.max_concurrent_executors,
            "provider": args.provider,
        }
        rag_store = None
        if args.rag:
            rag_cfg = load_rag_config()
            rag_store = QdrantRuleStore(
                QdrantClient(url=rag_cfg.qdrant_url),
                rag_cfg.collection,
                DashScopeEmbeddingClient(
                    api_key=rag_cfg.api_key,
                    base_url=rag_cfg.base_url,
                    model=rag_cfg.model,
                    dimensions=rag_cfg.dimensions,
                ),
            )
            rag_store.ensure_collection()
        controller = ReviewController(config, provider, cases=cases, rag_store=rag_store)
    except Exception as err:
        print(f"启动失败: {err}", file=sys.stderr)
        print("提示: --provider openai 需要 .env 配置 LLM_API_KEY/LLM_API_BASE_URL/LLM_DEFAULT_MODEL，或改用 --provider fake。", file=sys.stderr)
        return 1

    try:
        result = controller.run_until_done()
    except Exception as err:
        print(f"运行失败: {err}", file=sys.stderr)
        return 1

    if args.json:
        print(
            json.dumps(
                {
                    "sessionDir": result.sessionDir,
                    "reportPath": result.reportPath,
                    "findings": len(result.findings),
                    "tasks": len(result.tasks),
                    "metrics": result.metrics,
                },
                ensure_ascii=False,
                indent=2,
            )
        )
    else:
        print(f"档案室: {result.sessionDir}")
        print(f"任务:   {len(result.tasks)} 个，交卷 {len(result.outcomes)} 次")
        print(f"Findings: {len(result.findings)} 条")
        if result.metrics["totalCases"] > 0:
            print(
                f"评测:   命中 {result.metrics['hits']} / 误报 {result.metrics['falsePositives']}"
                f" / 无证据 {result.metrics['noEvidence']}"
                f"（标准答案 {result.metrics['totalCases']} 条）"
            )
        print(f"报告:   {result.reportPath}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
