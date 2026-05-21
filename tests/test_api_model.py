import httpx
from fastapi.testclient import TestClient
from pydantic import SecretStr

from agent_workflow.api.app import create_app
from agent_workflow.llm.openai_compatible import OpenAICompatibleChatClient


def test_model_settings_route_updates_runtime_client_without_exposing_key() -> None:
    app = create_app()
    # Force a client with no API key for this test
    app.state.chat_client = OpenAICompatibleChatClient(
        base_url="https://ark.cn-beijing.volces.com/api/v3",
        model="test-model",
        api_key=None,
    )
    client = TestClient(app)

    before = client.get("/model/settings")
    assert before.status_code == 200
    assert before.json()["api_key_configured"] is False

    updated = client.put(
        "/model/settings",
        json={
            "base_url": "https://ark.cn-beijing.volces.com/api/v3",
            "model": "doubao-seed-2-0-code-preview-260215",
            "api_key": "test-key",
        },
    )

    assert updated.status_code == 200
    assert updated.json()["api_key_configured"] is True
    assert "test-key" not in updated.text


def test_model_chat_route_uses_configured_client() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "id": "chatcmpl-test",
                "model": "doubao-seed-2-0-code-preview-260215",
                "choices": [{"message": {"content": "pong"}, "finish_reason": "stop"}],
                "usage": {},
            },
        )

    app = create_app()
    app.state.chat_client = OpenAICompatibleChatClient(
        base_url="https://ark.cn-beijing.volces.com/api/v3",
        model="doubao-seed-2-0-code-preview-260215",
        api_key=SecretStr("test-key"),
        client=httpx.Client(transport=httpx.MockTransport(handler)),
    )
    client = TestClient(app)

    response = client.post("/model/chat", json={"messages": [{"role": "user", "content": "ping"}]})

    assert response.status_code == 200
    assert response.json()["content"] == "pong"
