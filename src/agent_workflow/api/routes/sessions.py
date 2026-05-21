"""Session orchestration HTTP routes."""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status

from agent_workflow.api.dependencies import get_langgraph_runtime, get_orchestrator
from agent_workflow.orchestrator.langgraph_runtime import LangGraphSessionRuntime
from agent_workflow.orchestrator.models import (
    CreateSessionRequest,
    RunSessionRequest,
    RunSessionResult,
)
from agent_workflow.orchestrator.service import SessionOrchestrator
from agent_workflow.orchestrator.state import SessionState
from agent_workflow.tools.schemas import FunctionToolSpec

router = APIRouter(prefix="/sessions", tags=["sessions"])
OrchestratorDep = Annotated[SessionOrchestrator, Depends(get_orchestrator)]
LangGraphDep = Annotated[LangGraphSessionRuntime, Depends(get_langgraph_runtime)]


@router.post("", status_code=status.HTTP_201_CREATED)
def create_session(request: CreateSessionRequest, orchestrator: OrchestratorDep) -> SessionState:
    return orchestrator.create_session(user_id=request.user_id)


@router.get("/{thread_id}")
def get_session(thread_id: str, orchestrator: OrchestratorDep) -> SessionState:
    state = orchestrator.get_session(thread_id)
    if state is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="session not found")
    return state


@router.post("/run")
def run_session(request: RunSessionRequest, orchestrator: OrchestratorDep) -> RunSessionResult:
    return orchestrator.run(request)


@router.post("/run-langgraph")
def run_session_with_langgraph(
    request: RunSessionRequest,
    langgraph_runtime: LangGraphDep,
) -> RunSessionResult:
    return langgraph_runtime.run(request)


@router.get("/tools/list")
def list_tools(orchestrator: OrchestratorDep) -> list[FunctionToolSpec]:
    return orchestrator.tool_registry.list_specs()
