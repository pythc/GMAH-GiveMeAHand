"""Planner — decomposes user requests into actionable plans."""

from __future__ import annotations

import logging

from agent_workflow.agent.llm_client import AgentChatMessage, AgentLLMClient
from agent_workflow.agent.models import AgentStep, StepKind, ToolDefinition
from agent_workflow.agent.prompts import PLANNING_PROMPT, build_tools_description

logger = logging.getLogger(__name__)


class Planner:
    """Task decomposition planner that uses LLM to break down requests."""

    def __init__(self, llm: AgentLLMClient, temperature: float = 0.5) -> None:
        self._llm = llm
        self._temperature = temperature

    def plan(
        self,
        user_request: str,
        tools: list[ToolDefinition],
    ) -> AgentStep:
        """Generate a plan for the given request."""
        tools_desc = build_tools_description([t.model_dump() for t in tools])
        prompt = PLANNING_PROMPT.format(
            tools_description=tools_desc,
            user_request=user_request,
        )

        messages = [
            AgentChatMessage(role="system", content="You are a precise task planner."),
            AgentChatMessage(role="user", content=prompt),
        ]

        response = self._llm.simple_chat(messages, temperature=self._temperature)
        logger.info("Plan generated: %s", response[:200])

        return AgentStep(
            kind=StepKind.PLAN,
            content=response,
        )


class Reflector:
    """Self-reflection module that evaluates progress and suggests course corrections."""

    def __init__(self, llm: AgentLLMClient, temperature: float = 0.3) -> None:
        self._llm = llm
        self._temperature = temperature

    def reflect(
        self,
        user_request: str,
        trace_summary: str,
    ) -> AgentStep:
        """Reflect on progress so far and suggest next direction."""
        from agent_workflow.agent.prompts import REFLECTION_PROMPT

        prompt = REFLECTION_PROMPT.format(
            user_request=user_request,
            trace_so_far=trace_summary,
        )

        messages = [
            AgentChatMessage(
                role="system",
                content="You are a self-reflection module. Evaluate progress honestly.",
            ),
            AgentChatMessage(role="user", content=prompt),
        ]

        response = self._llm.simple_chat(messages, temperature=self._temperature)
        logger.info("Reflection: %s", response[:200])

        return AgentStep(
            kind=StepKind.REFLECT,
            content=response,
        )

    def should_reflect(self, steps: list[AgentStep], threshold: int = 4) -> bool:
        """Determine if reflection is needed based on step count and progress."""
        if len(steps) < threshold:
            return False

        # Count steps since last reflection or plan
        steps_since_reflection = 0
        for step in reversed(steps):
            if step.kind in (StepKind.REFLECT, StepKind.PLAN):
                break
            steps_since_reflection += 1

        return steps_since_reflection >= threshold
