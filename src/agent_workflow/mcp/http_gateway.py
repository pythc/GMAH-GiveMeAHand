"""Streamable-HTTP MCP gateway client with allowlist enforcement."""

from typing import Any
from uuid import uuid4

import httpx

from agent_workflow.mcp.config import McpGatewayConfig, McpServerConfig
from agent_workflow.mcp.gateway import McpCallResult, McpCapability, McpPrimitive


class McpGatewayError(RuntimeError):
    """Raised when an MCP request is blocked or fails."""


class StreamableHttpMcpGateway:
    """Minimal JSON-RPC over HTTP MCP client.

    The gateway enforces configured server and primitive allowlists before making
    network calls. It supports the standard MCP JSON-RPC methods used by tools,
    resources, and prompts discovery.
    """

    def __init__(self, config: McpGatewayConfig, client: httpx.Client | None = None) -> None:
        self.config = config
        self._client = client or httpx.Client()

    def list_capabilities(self) -> list[McpCapability]:
        capabilities: list[McpCapability] = []
        for server_name, server in self.config.servers.items():
            if not server.enabled:
                continue
            capabilities.extend(self._list_tools(server_name, server))
            capabilities.extend(self._list_resources(server_name, server))
            capabilities.extend(self._list_prompts(server_name, server))
        return capabilities

    def call_tool(
        self,
        server_name: str,
        tool_name: str,
        arguments: dict[str, Any],
    ) -> McpCallResult:
        server = self._require_server(server_name)
        self._require_allowed(tool_name, server.allow_tools, "tool")
        payload = self._rpc(server, "tools/call", {"name": tool_name, "arguments": arguments})
        return McpCallResult(
            server_name=server_name,
            name=tool_name,
            primitive=McpPrimitive.TOOL,
            payload=payload,
        )

    def read_resource(self, server_name: str, resource_name: str) -> McpCallResult:
        server = self._require_server(server_name)
        self._require_allowed(resource_name, server.allow_resources, "resource")
        payload = self._rpc(server, "resources/read", {"uri": resource_name})
        return McpCallResult(
            server_name=server_name,
            name=resource_name,
            primitive=McpPrimitive.RESOURCE,
            payload=payload,
        )

    def _list_tools(self, server_name: str, server: McpServerConfig) -> list[McpCapability]:
        result = self._rpc(server, "tools/list", {})
        tools = result.get("tools", [])
        if not isinstance(tools, list):
            return []
        return [
            McpCapability(
                server_name=server_name,
                name=str(tool.get("name")),
                primitive=McpPrimitive.TOOL,
                description=tool.get("description"),
                scopes=server.scopes,
                metadata={"schema": tool.get("inputSchema", {})},
            )
            for tool in tools
            if isinstance(tool, dict) and str(tool.get("name")) in server.allow_tools
        ]

    def _list_resources(self, server_name: str, server: McpServerConfig) -> list[McpCapability]:
        result = self._rpc(server, "resources/list", {})
        resources = result.get("resources", [])
        if not isinstance(resources, list):
            return []
        return [
            McpCapability(
                server_name=server_name,
                name=str(resource.get("uri")),
                primitive=McpPrimitive.RESOURCE,
                description=resource.get("description"),
                scopes=server.scopes,
                metadata={"mimeType": resource.get("mimeType")},
            )
            for resource in resources
            if isinstance(resource, dict) and str(resource.get("uri")) in server.allow_resources
        ]

    def _list_prompts(self, server_name: str, server: McpServerConfig) -> list[McpCapability]:
        result = self._rpc(server, "prompts/list", {})
        prompts = result.get("prompts", [])
        if not isinstance(prompts, list):
            return []
        return [
            McpCapability(
                server_name=server_name,
                name=str(prompt.get("name")),
                primitive=McpPrimitive.PROMPT,
                description=prompt.get("description"),
                scopes=server.scopes,
                metadata={"arguments": prompt.get("arguments", [])},
            )
            for prompt in prompts
            if isinstance(prompt, dict) and str(prompt.get("name")) in server.allow_prompts
        ]

    def _require_server(self, server_name: str) -> McpServerConfig:
        server = self.config.servers.get(server_name)
        if server is None or not server.enabled:
            raise McpGatewayError(f"MCP server is not enabled: {server_name}")
        if server.transport != "streamable_http":
            raise McpGatewayError(f"unsupported MCP transport: {server.transport}")
        return server

    def _require_allowed(self, name: str, allowed: list[str], primitive: str) -> None:
        if name not in allowed:
            raise McpGatewayError(f"MCP {primitive} is not allowlisted: {name}")

    def _rpc(self, server: McpServerConfig, method: str, params: dict[str, Any]) -> dict[str, Any]:
        request = {"jsonrpc": "2.0", "id": uuid4().hex, "method": method, "params": params}
        response = self._client.post(
            server.base_url,
            json=request,
            timeout=server.timeout_seconds,
            headers={"accept": "application/json"},
        )
        response.raise_for_status()
        payload = response.json()
        if "error" in payload:
            raise McpGatewayError(f"MCP error from {server.base_url}: {payload['error']}")
        result = payload.get("result", {})
        if not isinstance(result, dict):
            raise McpGatewayError("MCP result payload must be an object")
        return result
