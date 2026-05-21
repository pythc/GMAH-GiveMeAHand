"""Provider-neutral chat completion models."""

from typing import Any, Literal

from pydantic import BaseModel, Field

ChatRole = Literal["system", "user", "assistant", "tool"]


class ChatMessage(BaseModel):
    role: ChatRole
    content: str | list[dict[str, Any]]


class ChatCompletionRequest(BaseModel):
    messages: list[ChatMessage] = Field(min_length=1)
    model: str | None = None
    temperature: float | None = Field(default=None, ge=0, le=2)
    max_tokens: int | None = Field(default=None, ge=1)
    extra_body: dict[str, Any] = Field(default_factory=dict)


class ChatCompletionResult(BaseModel):
    model: str
    content: str
    finish_reason: str | None = None
    usage: dict[str, Any] = Field(default_factory=dict)
    raw_id: str | None = None
