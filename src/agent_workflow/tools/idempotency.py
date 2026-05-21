"""Idempotency helpers for side-effecting tool calls."""

import importlib
from typing import Any, Protocol

from agent_workflow.tools.schemas import FunctionToolSpec, ToolCallResult


class IdempotencyError(ValueError):
    """Raised when an idempotency key cannot be derived."""


class IdempotencyStore(Protocol):
    """Store completed tool-call results by idempotency key."""

    def get(self, key: str) -> ToolCallResult | None:
        """Return a previously recorded result, if any."""

    def record(self, key: str, result: ToolCallResult) -> None:
        """Record a successful tool-call result."""


class InMemoryIdempotencyStore:
    """Process-local idempotency store for MVP and tests."""

    def __init__(self) -> None:
        self._results: dict[str, ToolCallResult] = {}

    def get(self, key: str) -> ToolCallResult | None:
        result = self._results.get(key)
        return result.model_copy(deep=True) if result is not None else None

    def record(self, key: str, result: ToolCallResult) -> None:
        self._results[key] = result.model_copy(deep=True)


class RedisIdempotencyStore:
    """Redis-backed idempotency store for completed tool calls."""

    def __init__(self, redis_url: str, *, key_prefix: str = "agent:idempotency") -> None:
        redis_module = importlib.import_module("redis")
        self._client: Any = redis_module.Redis.from_url(redis_url, decode_responses=True)
        self._key_prefix = key_prefix

    def get(self, key: str) -> ToolCallResult | None:
        payload = self._client.get(self._key(key))
        if payload is None:
            return None
        return ToolCallResult.model_validate_json(str(payload))

    def record(self, key: str, result: ToolCallResult) -> None:
        self._client.set(self._key(key), result.model_dump_json())

    def _key(self, key: str) -> str:
        return f"{self._key_prefix}:{key}"


def build_idempotency_key(spec: FunctionToolSpec, arguments: dict[str, object]) -> str | None:
    """Build a stable key from a tool spec's configured argument fields."""

    if not spec.idempotency_key_source:
        return None
    fields = [field.strip() for field in spec.idempotency_key_source.split("+") if field.strip()]
    if not fields:
        raise IdempotencyError(f"empty idempotency key source for tool: {spec.name}")

    parts: list[str] = []
    for field in fields:
        if field not in arguments:
            raise IdempotencyError(f"missing idempotency field {field!r} for tool: {spec.name}")
        parts.append(f"{field}={arguments[field]}")
    return f"{spec.name}:" + "|".join(parts)
