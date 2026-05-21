"""Approval HTTP routes."""

from typing import Annotated

from fastapi import APIRouter, Depends

from agent_workflow.api.dependencies import get_orchestrator
from agent_workflow.orchestrator.models import ApprovalDecisionRequest, ApprovalDecisionResult
from agent_workflow.orchestrator.service import SessionOrchestrator
from agent_workflow.security.audit import ApprovalRecord

router = APIRouter(prefix="/approvals", tags=["approvals"])
OrchestratorDep = Annotated[SessionOrchestrator, Depends(get_orchestrator)]


@router.get("/pending")
def list_pending_approvals(orchestrator: OrchestratorDep) -> list[ApprovalRecord]:
    return orchestrator.list_pending_approvals()


@router.post("/{approval_id}/decide")
def decide_approval(
    approval_id: str,
    request: ApprovalDecisionRequest,
    orchestrator: OrchestratorDep,
) -> ApprovalDecisionResult:
    return orchestrator.decide_approval(
        approval_id,
        approved_by=request.approved_by,
        approved=request.approved,
        reason=request.reason,
    )
