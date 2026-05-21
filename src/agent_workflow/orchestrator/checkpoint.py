"""Checkpoint storage for durable session state."""

import importlib
from typing import Any, Protocol

from agent_workflow.orchestrator.state import SessionState


class CheckpointStore(Protocol):
    """Load and save thread-scoped session state."""

    def load(self, thread_id: str) -> SessionState | None:
        """Return a saved session state, if it exists."""

    def save(self, state: SessionState) -> None:
        """Persist session state."""


class InMemoryCheckpointStore:
    """Process-local checkpoint store for MVP and tests."""

    def __init__(self) -> None:
        self._states: dict[str, SessionState] = {}

    def load(self, thread_id: str) -> SessionState | None:
        state = self._states.get(thread_id)
        return state.model_copy(deep=True) if state is not None else None

    def save(self, state: SessionState) -> None:
        self._states[state.thread_id] = state.model_copy(deep=True)


class RedisCheckpointStore:
    """Redis-backed checkpoint store for thread-scoped session state."""

    def __init__(self, redis_url: str, *, key_prefix: str = "agent:checkpoint") -> None:
        redis_module = importlib.import_module("redis")
        self._client: Any = redis_module.Redis.from_url(redis_url, decode_responses=True)
        self._key_prefix = key_prefix

    def load(self, thread_id: str) -> SessionState | None:
        payload = self._client.get(self._key(thread_id))
        if payload is None:
            return None
        return SessionState.model_validate_json(str(payload))

    def save(self, state: SessionState) -> None:
        self._client.set(self._key(state.thread_id), state.model_dump_json())

    def _key(self, thread_id: str) -> str:
        return f"{self._key_prefix}:{thread_id}"
