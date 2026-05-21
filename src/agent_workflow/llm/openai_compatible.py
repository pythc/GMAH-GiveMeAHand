"""OpenAI-compatible chat completion client."""

from typing import Any

import httpx
from pydantic import SecretStr

from agent_workflow.llm.models import ChatCompletionRequest, ChatCompletionResult


class ChatModelError(RuntimeError):
    """Raised when a chat model call fails."""


class OpenAICompatibleChatClient:
    """Chat client for OpenAI-compatible providers such as Volcengine Ark."""

    def __init__(
        self,
        *,
        base_url: str,
        model: str,
        api_key: SecretStr | None,
        client: httpx.Client | None = None,
        timeout_seconds: float = 60,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.model = model
        self._api_key = api_key
        self._client = client or httpx.Client(timeout=timeout_seconds)

    @property
    def api_key_configured(self) -> bool:
        return self._api_key is not None

    @property
    def api_key_secret(self) -> SecretStr | None:
        return self._api_key

    def chat(
        self,
        request: ChatCompletionRequest,
        *,
        session_id: str = "",
    ) -> ChatCompletionResult:
        if self._api_key is None:
            raise ChatModelError("MODEL_API_KEY is required for chat model calls")

        model = request.model or self.model
        payload: dict[str, Any] = {
            "model": model,
            "messages": [message.model_dump() for message in request.messages],
            **request.extra_body,
        }
        if request.temperature is not None:
            payload["temperature"] = request.temperature
        if request.max_tokens is not None:
            payload["max_tokens"] = request.max_tokens

        # Log request
        _log_model_request(
            session_id=session_id,
            model=model,
            messages_count=len(request.messages),
            last_message=request.messages[-1] if request.messages else None,
        )

        try:
            response = self._client.post(
                f"{self.base_url}/chat/completions",
                json=payload,
                headers={"authorization": f"Bearer {self._api_key.get_secret_value()}"},
            )
            response.raise_for_status()
            body = response.json()
            result = _parse_chat_completion(body, model)
        except Exception as exc:
            _log_model_error(session_id=session_id, model=model, error=str(exc))
            raise

        # Log response
        _log_model_response(
            session_id=session_id,
            model=model,
            content=result.content,
            usage=result.usage,
        )
        return result


def _parse_chat_completion(body: dict[str, Any], fallback_model: str) -> ChatCompletionResult:
    choices = body.get("choices")
    if not isinstance(choices, list) or not choices:
        raise ChatModelError("chat completion response did not contain choices")

    first = choices[0]
    if not isinstance(first, dict):
        raise ChatModelError("chat completion choice must be an object")
    message = first.get("message")
    if not isinstance(message, dict):
        raise ChatModelError("chat completion choice did not contain a message")
    content = message.get("content")
    if not isinstance(content, str):
        raise ChatModelError("chat completion message content must be a string")

    usage = body.get("usage", {})
    if not isinstance(usage, dict):
        usage = {}

    return ChatCompletionResult(
        model=str(body.get("model") or fallback_model),
        content=content,
        finish_reason=first.get("finish_reason"),
        usage=usage,
        raw_id=body.get("id"),
    )


def _log_model_request(
    *,
    session_id: str,
    model: str,
    messages_count: int,
    last_message: Any,
) -> None:
    """Log model request to global activity store."""
    try:
        from agent_workflow.evaluation.tool_log import get_tool_log_store

        store = get_tool_log_store()
        # Extract preview from last message content
        preview = None
        if last_message is not None:
            content = last_message.content
            if isinstance(content, str):
                preview = content[:150]
            elif isinstance(content, list):
                # Multimodal — find first text block
                for block in content:
                    if isinstance(block, dict) and block.get("type") == "text":
                        preview = str(block.get("text", ""))[:150]
                        break
                if preview is None:
                    preview = f"[multimodal: {len(content)} blocks]"
        store.log_model_request(
            session_id=session_id or "api",
            model=model,
            messages_count=messages_count,
            prompt_preview=preview,
        )
    except Exception:  # noqa: BLE001 - logging must never break the main flow
        pass


def _log_model_response(
    *,
    session_id: str,
    model: str,
    content: str,
    usage: dict[str, Any],
) -> None:
    """Log model response to global activity store."""
    try:
        from agent_workflow.evaluation.tool_log import get_tool_log_store

        store = get_tool_log_store()
        # Try to detect if this is a tool call response
        parsed_tool = None
        if content.strip().startswith("{"):
            import json

            try:
                obj = json.loads(content[content.find("{"):content.rfind("}") + 1])
                parsed_tool = obj.get("tool")
            except (json.JSONDecodeError, ValueError):
                pass
        store.log_model_response(
            session_id=session_id or "api",
            model=model,
            content=content,
            usage=usage,
            parsed_tool=parsed_tool,
        )
    except Exception:  # noqa: BLE001 - logging must never break the main flow
        pass


def _log_model_error(*, session_id: str, model: str, error: str) -> None:
    """Log model call error to global activity store."""
    try:
        from agent_workflow.evaluation.tool_log import get_tool_log_store

        store = get_tool_log_store()
        store.log_error(session_id=session_id or "api", error=error, tool=f"llm:{model}")
    except Exception:  # noqa: BLE001
        pass
