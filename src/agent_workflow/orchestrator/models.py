"""Request and response models for session orchestration."""

from pydantic import BaseModel, Field

from agent_workflow.orchestrator.state import SessionState, ToolResult
from agent_workflow.security.audit import ApprovalRecord
from agent_workflow.tools.schemas import ToolCallRequest


class RunSessionRequest(BaseModel):
    """Run one turn in a thread, optionally with an explicit tool call."""

    thread_id: str | None = None
    user_id: str | None = None
    message: str = Field(default="", min_length=0)
    tool_call: ToolCallRequest | None = None


class RunSessionResult(BaseModel):
    """Result of a session turn."""

    thread_id: str
    trace_id: str
    state: SessionState
    tool_result: ToolResult | None = None
    approval_required: bool = False
    pending_approval: ApprovalRecord | None = None
    idempotent_replay: bool = False


class CreateSessionRequest(BaseModel):
    user_id: str | None = None


class ApprovalDecisionRequest(BaseModel):
    approved_by: str
    approved: bool
    reason: str | None = None


class ApprovalDecisionResult(BaseModel):
    approval: ApprovalRecord
    state: SessionState
    tool_result: ToolResult | None = None
    idempotent_replay: bool = False
