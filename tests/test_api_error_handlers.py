import httpx
from fastapi.testclient import TestClient
from pydantic import SecretStr

from agent_workflow.api.app import create_app
from agent_workflow.llm.openai_compatible import OpenAICompatibleChatClient
from agent_workflow.mcp.config import McpGatewayConfig, McpServerConfig
from agent_workflow.mcp.http_gateway import StreamableHttpMcpGateway


def test_model_chat_without_api_key_returns_structured_503() -> None:
    app = create_app()
    app.state.chat_client = OpenAICompatibleChatClient(
        base_url="https://ark.cn-beijing.volces.com/api/v3",
        model="test-model",
        api_key=None,
    )
    client = TestClient(app)
    response = client.post("/model/chat", json={"messages": [{"role": "user", "content": "ping"}]})

    assert response.status_code == 503
    assert response.json()["error"] == "chat_model_error"


def test_model_chat_upstream_401_returns_structured_502() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, json={"error": {"message": "invalid api key"}})

    app = create_app()
    app.state.chat_client = OpenAICompatibleChatClient(
        base_url="https://ark.cn-beijing.volces.com/api/v3",
        model="doubao-seed-2-0-code-preview-260215",
        api_key=SecretStr("bad-key"),
        client=httpx.Client(transport=httpx.MockTransport(handler)),
    )
    response = TestClient(app).post(
        "/model/chat",
        json={"messages": [{"role": "user", "content": "ping"}]},
    )

    assert response.status_code == 502
    assert response.json()["upstream_status"] == 401
    assert response.json()["detail"] == "invalid api key"


def test_mcp_unreachable_returns_structured_502() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused", request=request)

    app = create_app()
    app.state.mcp_gateway = StreamableHttpMcpGateway(
        McpGatewayConfig(
            servers={
                "grading": McpServerConfig(
                    base_url="http://mcp.test/mcp",
                    allow_tools=["fetch_submission"],
                )
            }
        ),
        httpx.Client(transport=httpx.MockTransport(handler)),
    )

    response = TestClient(app).post(
        "/mcp/tools/call",
        json={"server_name": "grading", "tool_name": "fetch_submission", "arguments": {}},
    )

    assert response.status_code == 502
    assert response.json()["error"] == "upstream_request_error"
