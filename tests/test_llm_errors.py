import httpx
import pytest
from pydantic import SecretStr

from agent_workflow.llm.models import ChatCompletionRequest, ChatMessage
from agent_workflow.llm.openai_compatible import (
    ChatModelError,
    OpenAICompatibleChatClient,
    _parse_chat_completion,
)


def test_chat_client_requires_api_key() -> None:
    client = OpenAICompatibleChatClient(
        base_url="https://ark.cn-beijing.volces.com/api/v3",
        model="doubao-seed-2-0-code-preview-260215",
        api_key=None,
    )

    with pytest.raises(ChatModelError):
        client.chat(ChatCompletionRequest(messages=[ChatMessage(role="user", content="ping")]))


@pytest.mark.parametrize(
    "body",
    [
        {},
        {"choices": []},
        {"choices": ["bad"]},
        {"choices": [{"message": None}]},
        {"choices": [{"message": {"content": 123}}]},
    ],
)
def test_parse_chat_completion_rejects_malformed_responses(body: dict[str, object]) -> None:
    with pytest.raises(ChatModelError):
        _parse_chat_completion(body, "fallback")


def test_parse_chat_completion_handles_missing_model_and_non_dict_usage() -> None:
    result = _parse_chat_completion(
        {
            "choices": [{"message": {"content": "ok"}, "finish_reason": "stop"}],
            "usage": "bad",
        },
        "fallback-model",
    )
    assert result.model == "fallback-model"
    assert result.usage == {}


def test_chat_client_raises_for_http_errors() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, json={"error": {"message": "unauthorized"}})

    client = OpenAICompatibleChatClient(
        base_url="https://ark.cn-beijing.volces.com/api/v3",
        model="doubao-seed-2-0-code-preview-260215",
        api_key=SecretStr("test-key"),
        client=httpx.Client(transport=httpx.MockTransport(handler)),
    )

    with pytest.raises(httpx.HTTPStatusError):
        client.chat(ChatCompletionRequest(messages=[ChatMessage(role="user", content="ping")]))
