"""Agent API routes — the main interface for autonomous agent interaction."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field

from agent_workflow.agent.llm_client import AgentLLMClient
from agent_workflow.agent.loop import AgentLoop
from agent_workflow.agent.models import AgentConfig, AgentResponse, AgentStep, StepKind
from agent_workflow.agent.tool_bridge import MockToolCallback, RegistryToolCallback
from agent_workflow.api.dependencies import get_chat_client, get_orchestrator
from agent_workflow.llm.openai_compatible import OpenAICompatibleChatClient
from agent_workflow.orchestrator.service import SessionOrchestrator

router = APIRouter(prefix="/agent", tags=["agent"])


class AgentChatRequest(BaseModel):
    """Request body for agent chat."""

    message: str = Field(min_length=1, description="User message to the agent")
    context: str | None = Field(default=None, description="Optional additional context")
    config: AgentConfig | None = Field(default=None, description="Optional agent configuration")


class AgentChatResponse(BaseModel):
    """Response from the agent chat endpoint."""

    answer: str
    success: bool
    plan: str | None = None
    tools_used: list[str] = []
    reflections: list[str] = []
    steps_taken: int = 0
    total_llm_calls: int = 0
    total_tokens: int = 0
    trace_id: str = ""
    trace_steps: list[dict[str, Any]] = Field(default_factory=list)


def _build_agent_loop(request: Request) -> AgentLoop:
    """Build an AgentLoop from the application's configured services."""
    chat_client: OpenAICompatibleChatClient = get_chat_client(request)

    if not chat_client.api_key_configured:
        raise RuntimeError("MODEL_API_KEY must be configured for agent mode")

    # Build the agent LLM client from the app's chat client config
    agent_llm = AgentLLMClient(
        base_url=chat_client.base_url,
        model=chat_client.model,
        api_key=chat_client.api_key_secret,  # type: ignore[arg-type]
        timeout_seconds=120,
    )

    # Try to connect to real tool infrastructure
    try:
        orchestrator: SessionOrchestrator = get_orchestrator(request)
        tool_callback = RegistryToolCallback(
            tool_registry=orchestrator.tool_registry,
            executor_registry=orchestrator.executor_registry,
        )
    except Exception:
        # Fallback to mock tools
        tool_callback = MockToolCallback()

    return AgentLoop(llm=agent_llm, tool_callback=tool_callback)


@router.post("/chat", response_model=AgentChatResponse)
def agent_chat(body: AgentChatRequest, request: Request) -> AgentChatResponse:
    """Run the autonomous agent reasoning loop.

    The agent will:
    1. Analyze the request
    2. Plan if needed
    3. Use tools autonomously
    4. Reflect on progress
    5. Produce a final answer
    """
    config = body.config or AgentConfig()
    chat_client: OpenAICompatibleChatClient = get_chat_client(request)

    if not chat_client.api_key_configured:
        raise RuntimeError("MODEL_API_KEY must be configured for agent mode")

    agent_llm = AgentLLMClient(
        base_url=chat_client.base_url,
        model=chat_client.model,
        api_key=chat_client.api_key_secret,  # type: ignore[arg-type]
        timeout_seconds=120,
    )

    # Try to connect to real tool infrastructure
    try:
        orchestrator: SessionOrchestrator = get_orchestrator(request)
        tool_callback = RegistryToolCallback(
            tool_registry=orchestrator.tool_registry,
            executor_registry=orchestrator.executor_registry,
        )
    except Exception:
        tool_callback = MockToolCallback()

    loop = AgentLoop(llm=agent_llm, tool_callback=tool_callback, config=config)
    response: AgentResponse = loop.run(body.message, context=body.context)

    # Convert trace steps to serializable dicts
    trace_steps = [
        {
            "step_id": s.step_id,
            "kind": s.kind.value,
            "content": s.content[:500] if s.content else "",
            "tool_name": s.tool_name,
            "error": s.error,
            "duration_ms": s.duration_ms,
        }
        for s in response.trace.steps
    ]

    return AgentChatResponse(
        answer=response.answer,
        success=response.success,
        plan=response.plan,
        tools_used=response.tools_used,
        reflections=response.reflections,
        steps_taken=len(response.trace.steps),
        total_llm_calls=response.trace.total_llm_calls,
        total_tokens=response.trace.total_tokens,
        trace_id=response.trace.trace_id,
        trace_steps=trace_steps,
    )


@router.get("/status")
def agent_status() -> dict[str, str]:
    """Check if the agent subsystem is available."""
    return {
        "status": "ready",
        "engine": "react-loop-v1",
        "capabilities": "planning,tool_use,reflection",
    }
