import httpx
import pytest

from agent_workflow.mcp.config import McpGatewayConfig, McpServerConfig
from agent_workflow.mcp.http_gateway import McpGatewayError, StreamableHttpMcpGateway


def test_mcp_gateway_rejects_disabled_and_unsupported_servers() -> None:
    disabled = StreamableHttpMcpGateway(
        McpGatewayConfig(
            servers={"disabled": McpServerConfig(base_url="http://mcp", enabled=False)}
        )
    )
    with pytest.raises(McpGatewayError):
        disabled.call_tool("disabled", "tool", {})

    unsupported = StreamableHttpMcpGateway(
        McpGatewayConfig(
            servers={
                "bad": McpServerConfig(
                    base_url="http://mcp",
                    transport="websocket",
                    allow_tools=["x"],
                )
            }
        )
    )
    with pytest.raises(McpGatewayError):
        unsupported.call_tool("bad", "x", {})


def test_mcp_gateway_raises_on_rpc_error_and_non_object_result() -> None:
    def error_handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"jsonrpc": "2.0", "id": "1", "error": {"message": "bad"}})

    gateway = StreamableHttpMcpGateway(
        McpGatewayConfig(servers={"s": McpServerConfig(base_url="http://mcp", allow_tools=["x"])}),
        httpx.Client(transport=httpx.MockTransport(error_handler)),
    )
    with pytest.raises(McpGatewayError):
        gateway.call_tool("s", "x", {})

    def list_handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"jsonrpc": "2.0", "id": "1", "result": []})

    gateway = StreamableHttpMcpGateway(
        McpGatewayConfig(servers={"s": McpServerConfig(base_url="http://mcp", allow_tools=["x"])}),
        httpx.Client(transport=httpx.MockTransport(list_handler)),
    )
    with pytest.raises(McpGatewayError):
        gateway.call_tool("s", "x", {})
