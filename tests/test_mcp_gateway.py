import json

import httpx
import pytest

from agent_workflow.mcp.config import McpGatewayConfig, McpServerConfig
from agent_workflow.mcp.gateway import McpPrimitive
from agent_workflow.mcp.http_gateway import McpGatewayError, StreamableHttpMcpGateway


def test_streamable_http_mcp_gateway_lists_and_calls_allowlisted_tools() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content)
        method = payload["method"]
        if method == "tools/list":
            result = {"tools": [{"name": "fetch_submission", "description": "Fetch"}]}
        elif method == "resources/list":
            result = {"resources": [{"uri": "rubric", "description": "Rubric"}]}
        elif method == "prompts/list":
            result = {"prompts": [{"name": "grading_review", "description": "Prompt"}]}
        elif method == "tools/call":
            result = {"content": [{"type": "text", "text": "ok"}]}
        else:
            result = {}
        return httpx.Response(200, json={"jsonrpc": "2.0", "id": payload["id"], "result": result})

    config = McpGatewayConfig(
        servers={
            "grading": McpServerConfig(
                base_url="http://mcp.test/mcp",
                allow_tools=["fetch_submission"],
                allow_resources=["rubric"],
                allow_prompts=["grading_review"],
            )
        }
    )
    gateway = StreamableHttpMcpGateway(config, httpx.Client(transport=httpx.MockTransport(handler)))

    capabilities = gateway.list_capabilities()
    result = gateway.call_tool("grading", "fetch_submission", {"submission_id": "sub-1"})

    assert {capability.primitive for capability in capabilities} == {
        McpPrimitive.TOOL,
        McpPrimitive.RESOURCE,
        McpPrimitive.PROMPT,
    }
    assert result.payload["content"][0]["text"] == "ok"


def test_streamable_http_mcp_gateway_blocks_unlisted_tool() -> None:
    config = McpGatewayConfig(
        servers={"grading": McpServerConfig(base_url="http://mcp.test/mcp", allow_tools=[])}
    )
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500)

    gateway = StreamableHttpMcpGateway(config, httpx.Client(transport=httpx.MockTransport(handler)))

    with pytest.raises(McpGatewayError):
        gateway.call_tool("grading", "publish_grade", {})
