import pytest

from agent_workflow.tools.executor import (
    CallableToolExecutor,
    ToolExecutionError,
    ToolExecutorRegistry,
)
from agent_workflow.tools.registry import ToolRegistry
from agent_workflow.tools.schemas import FunctionToolSpec, ToolCallRequest


def make_spec() -> FunctionToolSpec:
    return FunctionToolSpec(
        name="echo_tool",
        description="Echo arguments.",
        parameters={
            "type": "object",
            "additionalProperties": False,
            "properties": {"value": {"type": "string"}},
            "required": ["value"],
        },
    )


def test_callable_tool_executor_success_and_failure() -> None:
    def failing_handler(args: dict[str, object]) -> dict[str, object]:
        raise ZeroDivisionError("division by zero")

    executor = CallableToolExecutor("echo_tool", lambda args: {"echo": args["value"]})
    result = executor.execute(ToolCallRequest(tool_name="echo_tool", arguments={"value": "ok"}))
    assert result.accepted is True
    assert result.output == {"echo": "ok"}

    failed = CallableToolExecutor("echo_tool", failing_handler).execute(
        ToolCallRequest(tool_name="echo_tool", arguments={"value": "bad"})
    )
    assert failed.accepted is False
    assert "division" in (failed.error or "")

    with pytest.raises(ToolExecutionError):
        executor.execute(ToolCallRequest(tool_name="other_tool", arguments={"value": "x"}))


def test_tool_executor_registry_validates_and_routes() -> None:
    registry = ToolRegistry([make_spec()])
    executors = ToolExecutorRegistry(registry)
    executors.register("echo_tool", CallableToolExecutor("echo_tool", lambda args: dict(args)))

    result = executors.execute(ToolCallRequest(tool_name="echo_tool", arguments={"value": "ok"}))
    assert result.output == {"value": "ok"}

    with pytest.raises(ToolExecutionError):
        executors.register("echo_tool", CallableToolExecutor("echo_tool", lambda args: {}))
    with pytest.raises(ToolExecutionError):
        ToolExecutorRegistry(registry).execute(
            ToolCallRequest(tool_name="echo_tool", arguments={"value": "ok"})
        )
