"""Approval gate for high-risk tool calls."""

from datetime import UTC, datetime
from typing import Protocol
from uuid import uuid4

from agent_workflow.security.audit import ApprovalRecord
from agent_workflow.tools.schemas import (
    ApprovalPolicy,
    FunctionToolSpec,
    RiskLevel,
    ToolCallRequest,
)


class ApprovalError(ValueError):
    """Raised when an approval record cannot be found or decided."""


class ApprovalStore(Protocol):
    """Store pending and decided approval records."""

    def create(self, record: ApprovalRecord) -> ApprovalRecord:
        """Create an approval record."""

    def get(self, approval_id: str) -> ApprovalRecord:
        """Return an approval record by id."""

    def decide(
        self,
        approval_id: str,
        *,
        approved_by: str,
        approved: bool,
        reason: str | None = None,
    ) -> ApprovalRecord:
        """Approve or reject a pending approval."""

    def list_pending(self) -> list[ApprovalRecord]:
        """List records that have not been decided."""


class InMemoryApprovalStore:
    """Process-local approval store for MVP and tests."""

    def __init__(self) -> None:
        self._records: dict[str, ApprovalRecord] = {}

    def create(self, record: ApprovalRecord) -> ApprovalRecord:
        if record.approval_id in self._records:
            raise ApprovalError(f"approval already exists: {record.approval_id}")
        self._records[record.approval_id] = record.model_copy(deep=True)
        return record.model_copy(deep=True)

    def get(self, approval_id: str) -> ApprovalRecord:
        record = self._records.get(approval_id)
        if record is None:
            raise ApprovalError(f"unknown approval: {approval_id}")
        return record.model_copy(deep=True)

    def decide(
        self,
        approval_id: str,
        *,
        approved_by: str,
        approved: bool,
        reason: str | None = None,
    ) -> ApprovalRecord:
        record = self.get(approval_id)
        if record.approved is not None:
            raise ApprovalError(f"approval already decided: {approval_id}")
        decided = record.model_copy(
            update={
                "approved_by": approved_by,
                "approved": approved,
                "reason": reason,
                "decided_at": datetime.now(UTC),
            },
            deep=True,
        )
        self._records[approval_id] = decided
        return decided.model_copy(deep=True)

    def list_pending(self) -> list[ApprovalRecord]:
        return [
            record.model_copy(deep=True)
            for record in self._records.values()
            if record.approved is None
        ]


class ApprovalGate:
    """Decide whether a validated tool call must pause for human approval."""

    def __init__(self, store: ApprovalStore) -> None:
        self.store = store

    def requires_approval(self, spec: FunctionToolSpec) -> bool:
        return (
            spec.risk_level is RiskLevel.HIGH
            or spec.approval_policy is ApprovalPolicy.HUMAN_REQUIRED
        )

    def request_approval(
        self,
        *,
        spec: FunctionToolSpec,
        request: ToolCallRequest,
        requested_by: str,
        thread_id: str,
        trace_id: str,
        idempotency_key: str | None,
    ) -> ApprovalRecord:
        record = ApprovalRecord(
            approval_id=f"appr_{uuid4().hex}",
            tool_name=spec.name,
            requested_by=requested_by,
            call_id=request.call_id,
            thread_id=thread_id,
            trace_id=trace_id,
            arguments=request.arguments,
            idempotency_key=idempotency_key,
        )
        return self.store.create(record)
