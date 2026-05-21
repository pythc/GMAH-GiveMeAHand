"""Data models for the agentic reasoning core."""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, Field


class StepKind(StrEnum):
    """Classification of an agent reasoning step."""

    THINK = "think"
    PLAN = "plan"
    TOOL_CALL = "tool_call"
    TOOL_RESULT = "tool_result"
    REFLECT = "reflect"
    ANSWER = "answer"
    ERROR = "error"


class AgentStep(BaseModel):
    """A single step in the agent's reasoning trace."""

    step_id: str = Field(default_factory=lambda: f"step_{uuid4().hex[:12]}")
    kind: StepKind
    content: str = ""
    tool_name: str | None = None
    tool_arguments: dict[str, Any] | None = None
    tool_result: dict[str, Any] | None = None
    error: str | None = None
    timestamp: datetime = Field(default_factory=lambda: datetime.now(UTC))
    duration_ms: float | None = None

    @property
    def is_terminal(self) -> bool:
        return self.kind in (StepKind.ANSWER, StepKind.ERROR)


class AgentTrace(BaseModel):
    """Complete trace of an agent reasoning session."""

    trace_id: str = Field(default_factory=lambda: f"atrace_{uuid4().hex}")
    steps: list[AgentStep] = Field(default_factory=list)
    started_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    completed_at: datetime | None = None
    total_tokens: int = 0
    total_llm_calls: int = 0

    def append(self, step: AgentStep) -> None:
        self.steps.append(step)

    @property
    def is_complete(self) -> bool:
        return len(self.steps) > 0 and self.steps[-1].is_terminal

    def format_for_context(self) -> str:
        """Format the trace as a readable context block for the LLM."""
        lines: list[str] = []
        for i, step in enumerate(self.steps, 1):
            if step.kind == StepKind.THINK:
                lines.append(f"[Step {i} - Thinking] {step.content}")
            elif step.kind == StepKind.PLAN:
                lines.append(f"[Step {i} - Plan] {step.content}")
            elif step.kind == StepKind.TOOL_CALL:
                args_str = str(step.tool_arguments or {})
                lines.append(f"[Step {i} - Tool Call] {step.tool_name}({args_str})")
            elif step.kind == StepKind.TOOL_RESULT:
                lines.append(f"[Step {i} - Tool Result] {step.tool_name}: {step.content}")
            elif step.kind == StepKind.REFLECT:
                lines.append(f"[Step {i} - Reflection] {step.content}")
            elif step.kind == StepKind.ANSWER:
                lines.append(f"[Step {i} - Final Answer] {step.content}")
            elif step.kind == StepKind.ERROR:
                lines.append(f"[Step {i} - Error] {step.error or step.content}")
        return "\n".join(lines)


class ToolDefinition(BaseModel):
    """Tool definition in OpenAI function-calling format for the LLM."""

    name: str
    description: str
    parameters: dict[str, Any]


class AgentConfig(BaseModel):
    """Configuration for the agent reasoning loop."""

    max_steps: int = Field(default=15, ge=1, le=50)
    max_retries_per_tool: int = Field(default=2, ge=0, le=5)
    temperature: float = Field(default=0.3, ge=0, le=2)
    planning_temperature: float = Field(default=0.5, ge=0, le=2)
    reflection_threshold: int = Field(
        default=4,
        description="Trigger reflection after this many steps without an answer",
    )
    enable_planning: bool = True
    enable_reflection: bool = True
    model: str | None = None


class AgentResponse(BaseModel):
    """Final response from the agent reasoning loop."""

    answer: str
    trace: AgentTrace
    plan: str | None = None
    reflections: list[str] = Field(default_factory=list)
    tools_used: list[str] = Field(default_factory=list)
    success: bool = True
