"""Extended LLM client that supports function calling (tool_calls) for agentic use."""

from __future__ import annotations

import json
import logging
from typing import Any

import httpx
from pydantic import BaseModel, SecretStr

logger = logging.getLogger(__name__)


class ToolCallMessage(BaseModel):
    """A tool call request from the model."""

    id: str
    name: str
    arguments: dict[str, Any]


class AgentChatMessage(BaseModel):
    """Extended chat message supporting tool calls."""

    role: str  # system, user, assistant, tool
    content: str | None = None
    tool_calls: list[ToolCallMessage] | None = None
    tool_call_id: str | None = None  # For tool role messages
    name: str | None = None  # For tool role messages

    def to_api_dict(self) -> dict[str, Any]:
        """Convert to OpenAI API format."""
        msg: dict[str, Any] = {"role": self.role}
        if self.content is not None:
            msg["content"] = self.content
        if self.tool_calls:
            msg["tool_calls"] = [
                {
                    "id": tc.id,
                    "type": "function",
                    "function": {
                        "name": tc.name,
                        "arguments": json.dumps(tc.arguments, ensure_ascii=False),
                    },
                }
                for tc in self.tool_calls
            ]
        if self.tool_call_id is not None:
            msg["tool_call_id"] = self.tool_call_id
        if self.name is not None:
            msg["name"] = self.name
        return msg


class AgentChatResult(BaseModel):
    """Result from an agent-oriented chat call supporting tool_calls."""

    content: str | None = None
    tool_calls: list[ToolCallMessage] | None = None
    finish_reason: str | None = None
    usage: dict[str, Any] = {}
    model: str = ""
    raw_id: str | None = None

    @property
    def has_tool_calls(self) -> bool:
        return bool(self.tool_calls)

    @property
    def is_done(self) -> bool:
        return self.finish_reason == "stop" and not self.has_tool_calls


class AgentLLMClient:
    """LLM client with function-calling support for the agent reasoning loop."""

    def __init__(
        self,
        *,
        base_url: str,
        model: str,
        api_key: SecretStr,
        timeout_seconds: float = 120,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.model = model
        self._api_key = api_key
        self._client = httpx.Client(timeout=timeout_seconds)

    def chat(
        self,
        messages: list[AgentChatMessage],
        *,
        tools: list[dict[str, Any]] | None = None,
        temperature: float = 0.3,
        max_tokens: int | None = None,
        model: str | None = None,
    ) -> AgentChatResult:
        """Send a chat completion request with optional function calling."""
        model_name = model or self.model
        payload: dict[str, Any] = {
            "model": model_name,
            "messages": [m.to_api_dict() for m in messages],
            "temperature": temperature,
        }
        if max_tokens:
            payload["max_tokens"] = max_tokens
        if tools:
            payload["tools"] = tools

        logger.debug("Agent LLM call: model=%s, messages=%d, tools=%d",
                     model_name, len(messages), len(tools or []))

        response = self._client.post(
            f"{self.base_url}/chat/completions",
            json=payload,
            headers={"Authorization": f"Bearer {self._api_key.get_secret_value()}"},
        )
        response.raise_for_status()
        body = response.json()
        return self._parse_response(body, model_name)

    def simple_chat(
        self,
        messages: list[AgentChatMessage],
        *,
        temperature: float = 0.3,
        model: str | None = None,
    ) -> str:
        """Simple chat without tools — returns content string."""
        result = self.chat(messages, temperature=temperature, model=model)
        return result.content or ""

    def _parse_response(self, body: dict[str, Any], model: str) -> AgentChatResult:
        choices = body.get("choices", [])
        if not choices:
            return AgentChatResult(
                content="(no response from model)",
                finish_reason="error",
                model=model,
            )

        choice = choices[0]
        message = choice.get("message", {})
        finish_reason = choice.get("finish_reason")
        usage = body.get("usage", {})

        # Parse tool calls if present
        tool_calls: list[ToolCallMessage] | None = None
        raw_tool_calls = message.get("tool_calls")
        if raw_tool_calls and isinstance(raw_tool_calls, list):
            tool_calls = []
            for tc in raw_tool_calls:
                func = tc.get("function", {})
                args_str = func.get("arguments", "{}")
                try:
                    args = json.loads(args_str) if isinstance(args_str, str) else args_str
                except json.JSONDecodeError:
                    args = {"_raw": args_str}
                tool_calls.append(ToolCallMessage(
                    id=tc.get("id", ""),
                    name=func.get("name", ""),
                    arguments=args if isinstance(args, dict) else {"_raw": str(args)},
                ))

        return AgentChatResult(
            content=message.get("content"),
            tool_calls=tool_calls if tool_calls else None,
            finish_reason=finish_reason,
            usage=usage or {},
            model=str(body.get("model", model)),
            raw_id=body.get("id"),
        )

    def close(self) -> None:
        self._client.close()
