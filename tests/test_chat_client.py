import json

import httpx
from pydantic import SecretStr

from agent_workflow.llm.models import ChatCompletionRequest, ChatMessage
from agent_workflow.llm.openai_compatible import OpenAICompatibleChatClient


def test_openai_compatible_chat_client_calls_chat_completions() -> None:
    captured_headers: dict[str, str] = {}
    captured_json: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal captured_headers, captured_json
        captured_headers = dict(request.headers)
        captured_json = dict(json.loads(request.content))
        return httpx.Response(
            200,
            json={
                "id": "chatcmpl-test",
                "model": "doubao-seed-2-0-code-preview-260215",
                "choices": [
                    {
                        "message": {"role": "assistant", "content": "ok"},
                        "finish_reason": "stop",
                    }
                ],
                "usage": {"total_tokens": 3},
            },
        )

    client = OpenAICompatibleChatClient(
        base_url="https://ark.cn-beijing.volces.com/api/v3",
        model="doubao-seed-2-0-code-preview-260215",
        api_key=SecretStr("test-key"),
        client=httpx.Client(transport=httpx.MockTransport(handler)),
    )
    result = client.chat(
        ChatCompletionRequest(
            messages=[ChatMessage(role="user", content="ping")],
            temperature=0.2,
            max_tokens=16,
            extra_body={"metadata": {"trace_id": "trace-1"}},
        )
    )

    assert captured_headers["authorization"] == "Bearer test-key"
    assert captured_json["model"] == "doubao-seed-2-0-code-preview-260215"
    assert captured_json["temperature"] == 0.2
    assert captured_json["max_tokens"] == 16
    assert captured_json["metadata"] == {"trace_id": "trace-1"}
    assert result.content == "ok"
