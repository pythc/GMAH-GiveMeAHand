"""Audit event persistence boundary."""

from typing import Protocol

from agent_workflow.security.audit import AuditEvent


class AuditStore(Protocol):
    """Append-only audit event store."""

    def append(self, event: AuditEvent) -> None:
        """Persist an audit event."""

    def list_events(self, trace_id: str | None = None) -> list[AuditEvent]:
        """List events, optionally filtered by trace id."""


class InMemoryAuditStore:
    """Process-local audit store for MVP and tests."""

    def __init__(self) -> None:
        self._events: list[AuditEvent] = []

    def append(self, event: AuditEvent) -> None:
        self._events.append(event.model_copy(deep=True))

    def list_events(self, trace_id: str | None = None) -> list[AuditEvent]:
        events = self._events
        if trace_id is not None:
            events = [event for event in events if event.trace_id == trace_id]
        return [event.model_copy(deep=True) for event in events]
