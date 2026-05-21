"""In-memory function tool registry scaffold."""

from collections.abc import Iterable
from typing import Any

from jsonschema import Draft202012Validator

from agent_workflow.tools.schemas import FunctionToolSpec, ToolCallRequest, ToolCallResult


class ToolRegistryError(ValueError):
    """Raised when a tool cannot be registered or invoked."""


class ToolRegistry:
    """Register and validate tool specifications.

    This scaffold intentionally keeps execution as a mock boundary. Real side effects should be
    implemented behind adapters with approval, idempotency, and audit hooks.
    """

    def __init__(self, specs: Iterable[FunctionToolSpec] | None = None) -> None:
        self._specs: dict[str, FunctionToolSpec] = {}
        for spec in specs or []:
            self.register(spec)

    def register(self, spec: FunctionToolSpec) -> None:
        if spec.name in self._specs:
            raise ToolRegistryError(f"tool already registered: {spec.name}")
        self._specs[spec.name] = spec

    def get(self, name: str) -> FunctionToolSpec:
        try:
            return self._specs[name]
        except KeyError as exc:
            raise ToolRegistryError(f"unknown tool: {name}") from exc

    def list_specs(self) -> list[FunctionToolSpec]:
        return list(self._specs.values())

    def validate_arguments(self, tool_name: str, arguments: dict[str, Any]) -> None:
        spec = self.get(tool_name)
        Draft202012Validator(spec.parameters).validate(arguments)

    def execute_mock(self, request: ToolCallRequest) -> ToolCallResult:
        self.validate_arguments(request.tool_name, request.arguments)
        spec = self.get(request.tool_name)
        return ToolCallResult(
            tool_name=spec.name,
            accepted=True,
            output={
                "mock": True,
                "risk_level": spec.risk_level,
                "approval_policy": spec.approval_policy,
                "idempotency_key_source": spec.idempotency_key_source,
            },
        )
