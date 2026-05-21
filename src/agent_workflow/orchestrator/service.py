"""MVP session orchestrator that connects tools, approvals, idempotency, and audit."""

from datetime import UTC, datetime
from uuid import uuid4

from agent_workflow.orchestrator.checkpoint import CheckpointStore
from agent_workflow.orchestrator.models import (
    ApprovalDecisionResult,
    RunSessionRequest,
    RunSessionResult,
)
from agent_workflow.orchestrator.state import (
    ApprovalStatus,
    ConversationMessage,
    MessageRole,
    SessionState,
    ToolResult,
)
from agent_workflow.security.approval import ApprovalGate, ApprovalStore
from agent_workflow.security.audit import ApprovalRecord, AuditAction, AuditEvent
from agent_workflow.security.audit_store import AuditStore
from agent_workflow.tools.executor import ToolExecutorRegistry
from agent_workflow.tools.idempotency import IdempotencyStore, build_idempotency_key
from agent_workflow.tools.registry import ToolRegistry
from agent_workflow.tools.schemas import ToolCallRequest, ToolCallResult


class SessionOrchestratorError(RuntimeError):
    """Raised when a session turn cannot be orchestrated."""


class SessionOrchestrator:
    """Coordinate one-turn session execution for the MVP vertical slice."""

    def __init__(
        self,
        *,
        checkpoint_store: CheckpointStore,
        tool_registry: ToolRegistry,
        executor_registry: ToolExecutorRegistry,
        approval_gate: ApprovalGate,
        approval_store: ApprovalStore,
        idempotency_store: IdempotencyStore,
        audit_store: AuditStore,
    ) -> None:
        self.checkpoint_store = checkpoint_store
        self.tool_registry = tool_registry
        self.executor_registry = executor_registry
        self.approval_gate = approval_gate
        self.approval_store = approval_store
        self.idempotency_store = idempotency_store
        self.audit_store = audit_store

    def create_session(self, user_id: str | None = None) -> SessionState:
        state = SessionState(thread_id=f"thread_{uuid4().hex}", user_id=user_id)
        self.checkpoint_store.save(state)
        return state

    def get_session(self, thread_id: str) -> SessionState | None:
        return self.checkpoint_store.load(thread_id)

    def run(self, request: RunSessionRequest) -> RunSessionResult:
        trace_id = f"trace_{uuid4().hex}"
        state = self._load_or_create_state(request)

        if request.message:
            state.append_message(
                ConversationMessage(
                    role=MessageRole.USER,
                    content=request.message,
                    metadata={"trace_id": trace_id},
                )
            )

        tool_result: ToolResult | None = None
        pending_approval: ApprovalRecord | None = None
        idempotent_replay = False

        if request.tool_call is not None:
            normalized_call = self._with_call_id(request.tool_call)
            execution = self._prepare_or_execute_tool(
                state=state,
                request=normalized_call,
                trace_id=trace_id,
            )
            tool_result = execution.tool_result
            pending_approval = execution.pending_approval
            idempotent_replay = execution.idempotent_replay

        state.last_checkpoint_at = datetime.now(UTC)
        self.checkpoint_store.save(state)
        return RunSessionResult(
            thread_id=state.thread_id,
            trace_id=trace_id,
            state=state,
            tool_result=tool_result,
            approval_required=pending_approval is not None,
            pending_approval=pending_approval,
            idempotent_replay=idempotent_replay,
        )

    def decide_approval(
        self,
        approval_id: str,
        *,
        approved_by: str,
        approved: bool,
        reason: str | None = None,
    ) -> ApprovalDecisionResult:
        record = self.approval_store.decide(
            approval_id,
            approved_by=approved_by,
            approved=approved,
            reason=reason,
        )
        state = self._require_state(record.thread_id)
        action = AuditAction.TOOL_APPROVED if approved else AuditAction.TOOL_REJECTED
        self._audit(
            action=action,
            actor_id=approved_by,
            target=record.tool_name,
            trace_id=record.trace_id,
            metadata={"approval_id": approval_id, "reason": reason},
        )

        tool_result: ToolResult | None = None
        idempotent_replay = False
        if approved:
            if record.call_id is None:
                raise SessionOrchestratorError(f"approval has no call id: {approval_id}")
            call = ToolCallRequest(
                tool_name=record.tool_name,
                arguments=record.arguments,
                call_id=record.call_id,
            )
            result, idempotent_replay = self._execute_tool_call(
                state=state,
                request=call,
                trace_id=record.trace_id,
                idempotency_key=record.idempotency_key,
            )
            tool_result = result
            state.approval_status = ApprovalStatus.APPROVED
        else:
            state.approval_status = ApprovalStatus.REJECTED

        state.pending_approvals = [
            pending for pending in state.pending_approvals if pending.approval_id != approval_id
        ]
        state.last_checkpoint_at = datetime.now(UTC)
        self.checkpoint_store.save(state)
        return ApprovalDecisionResult(
            approval=record,
            state=state,
            tool_result=tool_result,
            idempotent_replay=idempotent_replay,
        )

    def list_pending_approvals(self) -> list[ApprovalRecord]:
        return self.approval_store.list_pending()

    def _load_or_create_state(self, request: RunSessionRequest) -> SessionState:
        if request.thread_id is None:
            return self.create_session(user_id=request.user_id)
        state = self.checkpoint_store.load(request.thread_id)
        if state is None:
            state = SessionState(thread_id=request.thread_id, user_id=request.user_id)
        elif request.user_id is not None and state.user_id is None:
            state.user_id = request.user_id
        return state

    def _require_state(self, thread_id: str) -> SessionState:
        state = self.checkpoint_store.load(thread_id)
        if state is None:
            raise SessionOrchestratorError(f"unknown thread: {thread_id}")
        return state

    def _with_call_id(self, request: ToolCallRequest) -> ToolCallRequest:
        if request.call_id is not None:
            return request
        return request.model_copy(update={"call_id": f"call_{uuid4().hex}"})

    def _prepare_or_execute_tool(
        self,
        *,
        state: SessionState,
        request: ToolCallRequest,
        trace_id: str,
    ) -> "_ToolExecutionStep":
        spec = self.tool_registry.get(request.tool_name)
        self.tool_registry.validate_arguments(request.tool_name, request.arguments)
        idempotency_key = build_idempotency_key(spec, request.arguments)

        if self.approval_gate.requires_approval(spec):
            pending = self.approval_gate.request_approval(
                spec=spec,
                request=request,
                requested_by=state.user_id or "anonymous",
                thread_id=state.thread_id,
                trace_id=trace_id,
                idempotency_key=idempotency_key,
            )
            state.pending_approvals.append(pending)
            state.approval_status = ApprovalStatus.PENDING
            self._audit(
                action=AuditAction.TOOL_APPROVAL_REQUESTED,
                actor_id=state.user_id or "anonymous",
                target=spec.name,
                trace_id=trace_id,
                metadata={"approval_id": pending.approval_id, "call_id": request.call_id},
            )
            return _ToolExecutionStep(pending_approval=pending)

        result, idempotent_replay = self._execute_tool_call(
            state=state,
            request=request,
            trace_id=trace_id,
            idempotency_key=idempotency_key,
        )
        return _ToolExecutionStep(tool_result=result, idempotent_replay=idempotent_replay)

    def _execute_tool_call(
        self,
        *,
        state: SessionState,
        request: ToolCallRequest,
        trace_id: str,
        idempotency_key: str | None,
    ) -> tuple[ToolResult, bool]:
        cached = self.idempotency_store.get(idempotency_key) if idempotency_key else None
        idempotent_replay = cached is not None
        call_result = cached if cached is not None else self.executor_registry.execute(request)

        if idempotency_key is not None and cached is None and call_result.accepted:
            self.idempotency_store.record(idempotency_key, call_result)

        tool_result = self._to_state_tool_result(request, call_result, idempotent_replay)
        state.tool_results.append(tool_result)
        state.updated_at = datetime.now(UTC)
        self._audit(
            action=AuditAction.TOOL_CALLED,
            actor_id=state.user_id or "anonymous",
            target=request.tool_name,
            trace_id=trace_id,
            metadata={
                "call_id": request.call_id,
                "accepted": call_result.accepted,
                "idempotency_key": idempotency_key,
                "idempotent_replay": idempotent_replay,
            },
        )
        return tool_result, idempotent_replay

    def _to_state_tool_result(
        self,
        request: ToolCallRequest,
        result: ToolCallResult,
        idempotent_replay: bool,
    ) -> ToolResult:
        output = dict(result.output)
        if idempotent_replay:
            output["idempotent_replay"] = True
        return ToolResult(
            tool_name=request.tool_name,
            call_id=request.call_id or f"call_{uuid4().hex}",
            status="accepted" if result.accepted else "failed",
            output=output,
            error=result.error,
        )

    def _audit(
        self,
        *,
        action: AuditAction,
        actor_id: str,
        target: str,
        trace_id: str,
        metadata: dict[str, object],
    ) -> None:
        self.audit_store.append(
            AuditEvent(
                action=action,
                actor_id=actor_id,
                target=target,
                trace_id=trace_id,
                metadata=metadata,
            )
        )


class _ToolExecutionStep:
    def __init__(
        self,
        *,
        tool_result: ToolResult | None = None,
        pending_approval: ApprovalRecord | None = None,
        idempotent_replay: bool = False,
    ) -> None:
        self.tool_result = tool_result
        self.pending_approval = pending_approval
        self.idempotent_replay = idempotent_replay
