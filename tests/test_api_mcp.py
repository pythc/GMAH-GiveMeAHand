import json

import httpx
from fastapi.testclient import TestClient

from agent_workflow.api.app import create_app
from agent_workflow.mcp.config import McpGatewayConfig, McpServerConfig
from agent_workflow.mcp.http_gateway import StreamableHttpMcpGateway


def test_api_mcp_routes_call_gateway() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content)
        method = payload["method"]
        if method == "tools/list":
            result = {"tools": [{"name": "fetch_submission", "description": "Fetch"}]}
        elif method == "resources/list":
            result = {"resources": [{"uri": "rubric", "description": "Rubric"}]}
        elif method == "prompts/list":
            result = {"prompts": []}
        elif method == "tools/call":
            result = {"content": [{"type": "text", "text": "tool-ok"}]}
        elif method == "resources/read":
            result = {"contents": [{"uri": "rubric", "text": "resource-ok"}]}
        else:
            result = {}
        return httpx.Response(200, json={"jsonrpc": "2.0", "id": payload["id"], "result": result})

    app = create_app()
    app.state.mcp_gateway = StreamableHttpMcpGateway(
        McpGatewayConfig(
            servers={
                "grading": McpServerConfig(
                    base_url="http://mcp.test/mcp",
                    allow_tools=["fetch_submission"],
                    allow_resources=["rubric"],
                )
            }
        ),
        httpx.Client(transport=httpx.MockTransport(handler)),
    )
    client = TestClient(app)

    assert client.get("/mcp/capabilities").status_code == 200
    tool = client.post(
        "/mcp/tools/call",
        json={"server_name": "grading", "tool_name": "fetch_submission", "arguments": {}},
    )
    resource = client.post(
        "/mcp/resources/read",
        json={"server_name": "grading", "resource_name": "rubric"},
    )

    assert tool.json()["payload"]["content"][0]["text"] == "tool-ok"
    assert resource.json()["payload"]["contents"][0]["text"] == "resource-ok"
