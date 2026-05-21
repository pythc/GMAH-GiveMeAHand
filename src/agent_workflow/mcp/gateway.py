"""MCP gateway interface models."""

from enum import StrEnum
from typing import Any, Protocol

from pydantic import BaseModel, Field


class McpPrimitive(StrEnum):
    TOOL = "tool"
    RESOURCE = "resource"
    PROMPT = "prompt"


class McpCapability(BaseModel):
    server_name: str
    name: str
    primitive: McpPrimitive
    description: str | None = None
    scopes: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


class McpCallResult(BaseModel):
    server_name: str
    name: str
    primitive: McpPrimitive
    payload: dict[str, Any] = Field(default_factory=dict)


class McpGateway(Protocol):
    def list_capabilities(self) -> list[McpCapability]:
        """Return tools, resources, and prompts exposed by configured MCP servers."""

    def call_tool(
        self,
        server_name: str,
        tool_name: str,
        arguments: dict[str, Any],
    ) -> McpCallResult:
        """Call an MCP tool through an approved server allowlist."""

    def read_resource(self, server_name: str, resource_name: str) -> McpCallResult:
        """Read an MCP resource through an approved server allowlist."""
