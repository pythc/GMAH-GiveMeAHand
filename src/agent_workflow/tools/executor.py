"""Execution boundary for function tools."""

from collections.abc import Callable
from typing import Any, Protocol

from agent_workflow.tools.registry import ToolRegistry
from agent_workflow.tools.schemas import ToolCallRequest, ToolCallResult


class ToolExecutionError(RuntimeError):
    """Raised when a tool executor fails."""


class ToolExecutor(Protocol):
    """Protocol implemented by side-effect adapters."""

    def execute(self, request: ToolCallRequest) -> ToolCallResult:
        """Execute a validated tool call."""


class CallableToolExecutor:
    """Wrap a callable as a tool executor."""

    def __init__(self, tool_name: str, handler: Callable[[dict[str, Any]], dict[str, Any]]) -> None:
        self.tool_name = tool_name
        self._handler = handler

    def execute(self, request: ToolCallRequest) -> ToolCallResult:
        if request.tool_name != self.tool_name:
            raise ToolExecutionError(f"executor {self.tool_name} cannot run {request.tool_name}")
        try:
            output = self._handler(request.arguments)
        except Exception as exc:  # noqa: BLE001 - execution boundary converts adapter errors.
            return ToolCallResult(tool_name=request.tool_name, accepted=False, error=str(exc))
        return ToolCallResult(tool_name=request.tool_name, accepted=True, output=output)


class ToolExecutorRegistry:
    """Bind validated tool specs to explicit executor adapters."""

    def __init__(self, tool_registry: ToolRegistry) -> None:
        self._tool_registry = tool_registry
        self._executors: dict[str, ToolExecutor] = {}

    def register(self, tool_name: str, executor: ToolExecutor) -> None:
        self._tool_registry.get(tool_name)
        if tool_name in self._executors:
            raise ToolExecutionError(f"executor already registered: {tool_name}")
        self._executors[tool_name] = executor

    def execute(self, request: ToolCallRequest) -> ToolCallResult:
        self._tool_registry.validate_arguments(request.tool_name, request.arguments)
        executor = self._executors.get(request.tool_name)
        if executor is None:
            raise ToolExecutionError(f"no executor registered for tool: {request.tool_name}")
        return executor.execute(request)
