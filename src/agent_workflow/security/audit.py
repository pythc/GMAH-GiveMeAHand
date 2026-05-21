"""Audit and approval models."""

from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field


class AuditAction(StrEnum):
    TOOL_APPROVAL_REQUESTED = "tool_approval_requested"
    TOOL_CALLED = "tool_called"
    TOOL_APPROVED = "tool_approved"
    TOOL_REJECTED = "tool_rejected"
    MESSAGE_SENT = "message_sent"
    MEMORY_WRITTEN = "memory_written"
    RAG_RETRIEVED = "rag_retrieved"


class AuditEvent(BaseModel):
    action: AuditAction
    actor_id: str
    target: str
    trace_id: str
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    metadata: dict[str, Any] = Field(default_factory=dict)
    redacted_fields: list[str] = Field(default_factory=list)


class ApprovalRecord(BaseModel):
    approval_id: str
    tool_name: str
    requested_by: str
    approved_by: str | None = None
    approved: bool | None = None
    reason: str | None = None
    call_id: str | None = None
    thread_id: str
    trace_id: str
    arguments: dict[str, Any] = Field(default_factory=dict)
    idempotency_key: str | None = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    decided_at: datetime | None = None
