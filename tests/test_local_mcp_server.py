from typing import Any, cast

from fastapi.testclient import TestClient

from agent_workflow.mcp.config import McpGatewayConfig, McpServerConfig
from agent_workflow.mcp.http_gateway import StreamableHttpMcpGateway
from agent_workflow.mcp.local_server import create_app


def rpc(client: TestClient, method: str, params: dict[str, object]) -> dict[str, Any]:
    response = client.post(
        "/mcp",
        json={"jsonrpc": "2.0", "id": "1", "method": method, "params": params},
    )
    assert response.status_code == 200
    return cast(dict[str, Any], response.json())


def test_local_mcp_server_lists_capabilities_and_calls_tools() -> None:
    client = TestClient(create_app())

    tools = cast(dict[str, Any], rpc(client, "tools/list", {})["result"])
    resources = cast(dict[str, Any], rpc(client, "resources/list", {})["result"])
    prompts = cast(dict[str, Any], rpc(client, "prompts/list", {})["result"])
    tool_call = cast(
        dict[str, Any],
        rpc(
            client,
            "tools/call",
            {"name": "fetch_submission", "arguments": {"submission_id": "submission-1"}},
        )["result"],
    )

    assert "fetch_submission" in {tool["name"] for tool in tools["tools"]}
    assert "rubric" in {resource["uri"] for resource in resources["resources"]}
    assert prompts["prompts"][0]["name"] == "grading_review"
    assert tool_call["structuredContent"]["submission_id"] == "submission-1"


def test_local_mcp_server_reads_resources_and_returns_errors() -> None:
    client = TestClient(create_app())

    rubric = cast(dict[str, Any], rpc(client, "resources/read", {"uri": "rubric"})["result"])
    unknown = rpc(client, "tools/call", {"name": "missing", "arguments": {}})

    assert rubric["contents"][0]["uri"] == "rubric"
    assert unknown["error"]["code"] == -32000


def test_streamable_gateway_can_call_local_mcp_server() -> None:
    app = create_app()
    test_client = TestClient(app)

    class LocalTransport:
        def post(
            self,
            url: str,
            *,
            json: dict[str, object],
            timeout: float,
            headers: dict[str, str],
        ) -> Any:
            return test_client.post("/mcp", json=json)

    gateway = StreamableHttpMcpGateway(
        McpGatewayConfig(
            servers={
                "grading-system": McpServerConfig(
                    base_url="http://local.test/mcp",
                    allow_tools=["fetch_submission"],
                    allow_resources=["rubric"],
                    allow_prompts=["grading_review"],
                )
            }
        ),
        client=LocalTransport(),  # type: ignore[arg-type]
    )

    capabilities = gateway.list_capabilities()
    result = gateway.call_tool(
        "grading-system",
        "fetch_submission",
        {"submission_id": "submission-1"},
    )

    assert len(capabilities) == 3
    assert result.payload["structuredContent"]["submission_id"] == "submission-1"
