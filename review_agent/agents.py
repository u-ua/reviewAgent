"""角色工具箱（对应 src/agents.ts）。

角色权限 = 工具箱不同：
- Planner（审查经理）：只有 planner_submit，看的是 goal/scope/任务摘要/交卷摘要，
  工具箱里没有 read_file / grep / finding_write —— 它根本看不到源码。
- Executor（审查员工）：只读仓库工具 + finding_write + task_result_submit，
  没有建任务、改 scope 的工具。
"""

from __future__ import annotations

from .tools.finding import build_finding_write_tool
from .tools.read_only import create_read_only_tools
from .tools.rule_search import build_rule_search_tool
from .tools.submit import build_planner_submit_tool, build_task_result_submit_tool
from .types import Tool


def create_planner_tools() -> list[Tool]:
    return [build_planner_submit_tool()]


def create_executor_tools(*, include_rag: bool = False) -> list[Tool]:
    tools = create_read_only_tools()
    if include_rag:
        tools.append(build_rule_search_tool())
    return tools + [
        build_finding_write_tool(),
        build_task_result_submit_tool(),
    ]
