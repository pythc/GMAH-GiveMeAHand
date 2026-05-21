import pytest

from agent_workflow.security.approval import ApprovalError, ApprovalGate, InMemoryApprovalStore
from agent_workflow.security.audit import ApprovalRecord, AuditAction, AuditEvent
from agent_workflow.security.audit_store import InMemoryAuditStore
from agent_workflow.tools.schemas import (
    ApprovalPolicy,
    FunctionToolSpec,
    RiskLevel,
    ToolCallRequest,
)


def make_approval_record(approval_id: str = "appr-1") -> ApprovalRecord:
    return ApprovalRecord(
        approval_id=approval_id,
        tool_name="publish_grade",
        requested_by="teacher-1",
        thread_id="thread-1",
        trace_id="trace-1",
        arguments={"submission_id": "submission-1"},
    )


def test_in_memory_approval_store_lifecycle_and_errors() -> None:
    store = InMemoryApprovalStore()
    record = make_approval_record()

    created = store.create(record)
    assert created.approval_id == "appr-1"
    assert store.list_pending()[0].approval_id == "appr-1"

    with pytest.raises(ApprovalError):
        store.create(record)
    with pytest.raises(ApprovalError):
        store.get("missing")

    decided = store.decide("appr-1", approved_by="reviewer-1", approved=False, reason="bad")
    assert decided.approved is False
    assert decided.decided_at is not None
    assert store.list_pending() == []

    with pytest.raises(ApprovalError):
        store.decide("appr-1", approved_by="reviewer-2", approved=True)


def test_approval_gate_requests_human_approval_record() -> None:
    store = InMemoryApprovalStore()
    gate = ApprovalGate(store)
    spec = FunctionToolSpec(
        name="publish_grade",
        description="Publish grade.",
        risk_level=RiskLevel.HIGH,
        approval_policy=ApprovalPolicy.HUMAN_REQUIRED,
        idempotency_key_source="submission_id",
        parameters={
            "type": "object",
            "additionalProperties": False,
            "properties": {"submission_id": {"type": "string"}},
            "required": ["submission_id"],
        },
    )
    record = gate.request_approval(
        spec=spec,
        request=ToolCallRequest(
            tool_name="publish_grade",
            arguments={"submission_id": "submission-1"},
            call_id="call-1",
        ),
        requested_by="teacher-1",
        thread_id="thread-1",
        trace_id="trace-1",
        idempotency_key="key-1",
    )

    assert gate.requires_approval(spec) is True
    assert record.call_id == "call-1"
    assert record.idempotency_key == "key-1"
    assert store.get(record.approval_id).arguments["submission_id"] == "submission-1"


def test_in_memory_audit_store_filters_and_returns_copies() -> None:
    store = InMemoryAuditStore()
    event = AuditEvent(
        action=AuditAction.TOOL_CALLED,
        actor_id="teacher-1",
        target="save_feedback_draft",
        trace_id="trace-1",
    )
    store.append(event)
    store.append(event.model_copy(update={"trace_id": "trace-2"}))

    filtered = store.list_events("trace-1")
    assert len(filtered) == 1
    assert filtered[0] == event
    assert filtered[0] is not event
    assert len(store.list_events()) == 2
