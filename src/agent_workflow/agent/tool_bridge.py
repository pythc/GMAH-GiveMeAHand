"""Bridge between the AgentLoop and existing tool/orchestrator infrastructure."""

from __future__ import annotations

from typing import Any

from agent_workflow.agent.loop import ToolExecutionCallback
from agent_workflow.agent.models import ToolDefinition
from agent_workflow.tools.executor import ToolExecutorRegistry
from agent_workflow.tools.registry import ToolRegistry
from agent_workflow.tools.schemas import FunctionToolSpec, ToolCallRequest


class RegistryToolCallback(ToolExecutionCallback):
    """Connects the agent reasoning loop to the existing ToolRegistry + ExecutorRegistry.

    This bridges the abstract ToolExecutionCallback interface to the real
    tool infrastructure with schema validation, risk levels, and execution.
    """

    def __init__(
        self,
        tool_registry: ToolRegistry,
        executor_registry: ToolExecutorRegistry,
    ) -> None:
        self._tool_registry = tool_registry
        self._executor_registry = executor_registry

    def execute(self, tool_name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        """Execute a tool through the registry infrastructure."""
        # Validate schema before execution
        self._tool_registry.validate_arguments(tool_name, arguments)

        request = ToolCallRequest(tool_name=tool_name, arguments=arguments)
        result = self._executor_registry.execute(request)

        if not result.accepted:
            raise RuntimeError(
                f"Tool '{tool_name}' execution failed: {result.error or 'unknown error'}"
            )
        return result.output

    def list_tools(self) -> list[ToolDefinition]:
        """Convert registered FunctionToolSpecs to ToolDefinitions for the agent."""
        specs = self._tool_registry.list_specs()
        return [self._spec_to_definition(spec) for spec in specs]

    def _spec_to_definition(self, spec: FunctionToolSpec) -> ToolDefinition:
        # Include risk/approval info in description so agent knows about constraints
        desc = spec.description
        if spec.risk_level.value != "low":
            desc += f" [Risk: {spec.risk_level.value}]"
        if spec.approval_policy.value != "none":
            desc += f" [Approval: {spec.approval_policy.value}]"
        return ToolDefinition(
            name=spec.name,
            description=desc,
            parameters=spec.parameters,
        )


class MockToolCallback(ToolExecutionCallback):
    """A mock tool callback for testing the agent without real tool infrastructure."""

    def __init__(self, tools: list[ToolDefinition] | None = None) -> None:
        self._tools = tools or self._default_tools()
        self._call_history: list[tuple[str, dict[str, Any]]] = []

    def execute(self, tool_name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        """Mock execute — records the call and returns synthetic results."""
        self._call_history.append((tool_name, arguments))

        # Provide meaningful mock responses based on tool name
        mock_responses: dict[str, dict[str, Any]] = {
            "search": {"results": [{"title": "Example result", "snippet": "This is relevant info."}]},
            "calculate": {"result": 42, "expression": str(arguments)},
            "get_weather": {"temperature": 22, "condition": "sunny", "city": arguments.get("city", "unknown")},
            "fetch_assignment": {"assignment_id": arguments.get("assignment_id"), "title": "Test Assignment", "due_date": "2025-06-01"},
            "fetch_rubric": {"rubric_version": arguments.get("rubric_version"), "criteria": ["clarity", "depth", "originality"]},
            "fetch_submission": {"submission_id": arguments.get("submission_id"), "content": "Sample student submission text."},
        }
        return mock_responses.get(tool_name, {"status": "ok", "tool": tool_name, "args": arguments})

    def list_tools(self) -> list[ToolDefinition]:
        return self._tools

    def _default_tools(self) -> list[ToolDefinition]:
        return [
            ToolDefinition(
                name="search",
                description="Search for information on a topic",
                parameters={
                    "type": "object",
                    "properties": {"query": {"type": "string", "description": "Search query"}},
                    "required": ["query"],
                    "additionalProperties": False,
                },
            ),
            ToolDefinition(
                name="calculate",
                description="Perform a mathematical calculation",
                parameters={
                    "type": "object",
                    "properties": {"expression": {"type": "string", "description": "Math expression"}},
                    "required": ["expression"],
                    "additionalProperties": False,
                },
            ),
            ToolDefinition(
                name="get_weather",
                description="Get current weather for a city",
                parameters={
                    "type": "object",
                    "properties": {"city": {"type": "string", "description": "City name"}},
                    "required": ["city"],
                    "additionalProperties": False,
                },
            ),
        ]
