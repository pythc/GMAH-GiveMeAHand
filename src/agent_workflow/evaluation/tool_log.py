"""Shared agent activity log — captures tool calls, model responses, progress, errors."""

from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field


class LogKind(StrEnum):
    """Type of log entry."""

    TOOL_CALL = "tool_call"
    MODEL_REQUEST = "model_request"
    MODEL_RESPONSE = "model_response"
    PROGRESS = "progress"
    ERROR = "error"
    SYSTEM = "system"


class ActivityLogEntry(BaseModel):
    """Single activity log entry."""

    timestamp: str = Field(
        default_factory=lambda: datetime.now(UTC).isoformat(timespec="seconds")
    )
    kind: LogKind
    session_id: str = ""
    tool: str | None = None
    target: str | None = None
    status: str | None = None
    content: str | None = None
    detail: str | None = None
    arguments: dict[str, Any] = Field(default_factory=dict)
    metadata: dict[str, Any] = Field(default_factory=dict)


# Keep backward compatibility
ToolLogEntry = ActivityLogEntry


class ActivityLogStore:
    """In-memory capped activity log, shared by console evaluation and QQ channel."""

    def __init__(self, max_entries: int = 3000) -> None:
        self._logs: list[ActivityLogEntry] = []
        self._max_entries = max_entries

    def append(self, entry: ActivityLogEntry) -> None:
        self._logs.append(entry)
        if len(self._logs) > self._max_entries:
            del self._logs[: len(self._logs) - self._max_entries]

    def log_tool_call(
        self,
        *,
        session_id: str,
        tool: str,
        arguments: dict[str, Any],
        result: dict[str, Any],
    ) -> None:
        """Log a tool invocation and its result."""
        target = _extract_target(arguments)
        status = "success" if result.get("ok") else "failed"
        detail = str(
            result.get("error") or result.get("message") or result.get("reason") or ""
        )[:500]
        self.append(
            ActivityLogEntry(
                kind=LogKind.TOOL_CALL,
                session_id=session_id,
                tool=tool,
                target=target,
                status=status,
                detail=detail or None,
                arguments=arguments,
            )
        )

    # Backward compatible alias
    log = log_tool_call

    def log_model_request(
        self,
        *,
        session_id: str,
        messages_count: int,
        model: str | None = None,
        prompt_preview: str | None = None,
    ) -> None:
        """Log a model API request being sent."""
        self.append(
            ActivityLogEntry(
                kind=LogKind.MODEL_REQUEST,
                session_id=session_id,
                tool="llm",
                target=model,
                status="sending",
                content=prompt_preview[:200] if prompt_preview else None,
                metadata={"messages_count": messages_count},
            )
        )

    def log_model_response(
        self,
        *,
        session_id: str,
        content: str,
        model: str | None = None,
        usage: dict[str, Any] | None = None,
        parsed_tool: str | None = None,
    ) -> None:
        """Log a model response received."""
        self.append(
            ActivityLogEntry(
                kind=LogKind.MODEL_RESPONSE,
                session_id=session_id,
                tool=parsed_tool or "llm",
                target=model,
                status="received",
                content=content[:500],
                metadata=usage or {},
            )
        )

    def log_progress(
        self,
        *,
        session_id: str,
        message: str,
        sent: bool = False,
    ) -> None:
        """Log a progress message (sent to user or internal)."""
        self.append(
            ActivityLogEntry(
                kind=LogKind.PROGRESS,
                session_id=session_id,
                tool="send_progress",
                status="sent" if sent else "generated",
                content=message[:300],
            )
        )

    def log_error(
        self,
        *,
        session_id: str,
        error: str,
        tool: str | None = None,
    ) -> None:
        """Log an error event."""
        self.append(
            ActivityLogEntry(
                kind=LogKind.ERROR,
                session_id=session_id,
                tool=tool,
                status="error",
                detail=error[:500],
            )
        )

    def log_system(
        self,
        *,
        session_id: str,
        message: str,
    ) -> None:
        """Log a system event (start, end, etc.)."""
        self.append(
            ActivityLogEntry(
                kind=LogKind.SYSTEM,
                session_id=session_id,
                status="info",
                content=message[:300],
            )
        )

    def list(
        self,
        limit: int = 200,
        session_id: str | None = None,
        kind: LogKind | None = None,
    ) -> list[ActivityLogEntry]:
        entries = self._logs
        if session_id:
            entries = [e for e in entries if e.session_id == session_id]
        if kind:
            entries = [e for e in entries if e.kind == kind]
        return entries[-max(1, min(limit, 1000)):]

    def clear(self) -> None:
        self._logs.clear()

    @property
    def count(self) -> int:
        return len(self._logs)


def _extract_target(arguments: dict[str, Any]) -> str | None:
    for key in ("url", "path", "query", "topic_name"):
        value = arguments.get(key)
        if value:
            return str(value)[:120]
    message = arguments.get("message")
    return str(message)[:60] if message else None


# Singleton shared instance
_global_activity_log_store = ActivityLogStore()


def get_tool_log_store() -> ActivityLogStore:
    """Return the process-global activity log store."""
    return _global_activity_log_store
