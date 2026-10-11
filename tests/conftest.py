"""测试共享工具（对应 tests/helpers.ts）。"""

from __future__ import annotations

import tempfile
from pathlib import Path

from review_agent.stores.artifact_store import ArtifactStore
from review_agent.stores.execution_log import ExecutionLog
from review_agent.stores.finding_store import FindingStore
from review_agent.stores.task_store import TaskStore
from review_agent.types import Stores, ToolContext

REPO_ROOT = Path(__file__).resolve().parent.parent


def make_session_dir() -> str:
    return tempfile.mkdtemp(prefix="review-agent-test-")


def make_ctx(
    repo_root: str,
    scope: list[str],
    session_dir: str | None = None,
    task_id: str | None = None,
    task_dimension: str = "security",
) -> ToolContext:
    session_dir = session_dir or make_session_dir()
    run_id = Path(session_dir).name
    return ToolContext(
        runId=run_id,
        taskId=task_id,
        taskDimension=task_dimension,
        repoRoot=repo_root,
        scope=scope,
        stores=Stores(
            executionLog=ExecutionLog(str(Path(session_dir) / "execution.jsonl")),
            artifactStore=ArtifactStore(
                artifacts_dir=str(Path(session_dir) / "artifacts"),
                run_id=run_id,
            ),
            findingStore=FindingStore(str(Path(session_dir) / "findings.json")),
            taskStore=TaskStore(str(Path(session_dir) / "tasks.json")),
        ),
    )


def demo_repo_root() -> str:
    """测试用 demo 仓库根（绝对路径）。"""
    return str(REPO_ROOT / "fixtures" / "demo-repo")
