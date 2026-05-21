"""State models for durable session orchestration."""

from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field

from agent_workflow.security.audit import ApprovalRecord


class MessageRole(StrEnum):
    USER = "user"
    ASSISTANT = "assistant"
    TOOL = "tool"
    SYSTEM = "system"


class ApprovalStatus(StrEnum):
    NOT_REQUIRED = "not_required"
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"


class ConversationMessage(BaseModel):
    role: MessageRole
    content: str
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    metadata: dict[str, Any] = Field(default_factory=dict)


class ToolResult(BaseModel):
    tool_name: str
    call_id: str
    status: str
    output: dict[str, Any] = Field(default_factory=dict)
    error: str | None = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class SessionState(BaseModel):
    thread_id: str
    user_id: str | None = None
    messages: list[ConversationMessage] = Field(default_factory=list)
    tool_results: list[ToolResult] = Field(default_factory=list)
    pending_approvals: list[ApprovalRecord] = Field(default_factory=list)
    approval_status: ApprovalStatus = ApprovalStatus.NOT_REQUIRED
    summary_ref: str | None = None
    memory_refs: list[str] = Field(default_factory=list)
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    last_checkpoint_at: datetime | None = None

    def append_message(self, message: ConversationMessage) -> None:
        self.messages.append(message)
        self.updated_at = datetime.now(UTC)
