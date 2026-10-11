import pytest

from review_agent.prompts import (
    LOGIC_EXECUTOR_PROMPT,
    PERFORMANCE_EXECUTOR_PROMPT,
    SECURITY_EXECUTOR_PROMPT,
    get_executor_system_prompt,
    render_executor_input,
)


@pytest.mark.parametrize(
    "dimension,prompt,marker",
    [
        ("security", SECURITY_EXECUTOR_PROMPT, "不可信输入到危险 Sink"),
        ("performance", PERFORMANCE_EXECUTOR_PROMPT, "N+1 查询"),
        ("logic", LOGIC_EXECUTOR_PROMPT, "边界值"),
    ],
)
def test_dimension_prompts_keep_common_protocol_and_specific_focus(dimension, prompt, marker):
    assert get_executor_system_prompt(dimension) == prompt
    assert "read_file 或 git_diff" in prompt
    assert "task_result_submit" in prompt
    assert "严格遵守本 Executor 的审查维度" in prompt
    assert marker in prompt


def test_unknown_dimension_is_rejected():
    with pytest.raises(ValueError, match="未知审查维度"):
        get_executor_system_prompt("style")


def test_executor_input_renders_dimension():
    rendered = render_executor_input({
        "taskId": "task:perf", "goal": "检查性能", "dimension": "performance",
        "successCriteria": [], "scopeRef": ["src"], "dependsOnTaskRefs": [],
        "budget": {"maxTurns": 5},
    })
    assert "审查维度: performance" in rendered
