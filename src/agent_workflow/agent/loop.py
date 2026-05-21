"""Core ReAct reasoning loop — the agent's autonomous decision-making engine.

This module implements the Observe-Think-Act-Reflect cycle that makes the agent
truly autonomous. The LLM drives all decisions: what tool to call, when to reflect,
and when to deliver a final answer.
"""

from __future__ import annotations

import json
import logging
import time
from datetime import UTC, datetime
from typing import Any

from agent_workflow.agent.llm_client import AgentChatMessage, AgentLLMClient, ToolCallMessage
from agent_workflow.agent.models import (
    AgentConfig,
    AgentResponse,
    AgentStep,
    AgentTrace,
    StepKind,
    ToolDefinition,
)
from agent_workflow.agent.planner import Planner, Reflector
from agent_workflow.agent.prompts import AGENT_SYSTEM_PROMPT

logger = logging.getLogger(__name__)


class ToolExecutionCallback:
    """Protocol for executing tools — decouples agent from specific tool infrastructure."""

    def execute(self, tool_name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        """Execute a tool and return the result dict."""
        raise NotImplementedError

    def list_tools(self) -> list[ToolDefinition]:
        """Return available tool definitions."""
        raise NotImplementedError


class AgentLoop:
    """The autonomous reasoning engine.

    Implements a ReAct-style loop where the LLM:
    1. Observes the current state (user request + trace history)
    2. Thinks/plans about what to do
    3. Acts (calls a tool or produces a final answer)
    4. Reflects on results when needed

    The loop continues until the LLM produces a final answer or hits max_steps.
    """

    def __init__(
        self,
        *,
        llm: AgentLLMClient,
        tool_callback: ToolExecutionCallback,
        config: AgentConfig | None = None,
    ) -> None:
        self._llm = llm
        self._tools = tool_callback
        self._config = config or AgentConfig()
        self._planner = Planner(llm, temperature=self._config.planning_temperature)
        self._reflector = Reflector(llm, temperature=self._config.temperature)

    def run(self, user_message: str, *, context: str | None = None) -> AgentResponse:
        """Run the full reasoning loop for a user request.

        Args:
            user_message: The user's request/question.
            context: Optional additional context (memory, RAG results, etc.)

        Returns:
            AgentResponse with the final answer and full reasoning trace.
        """
        trace = AgentTrace()
        available_tools = self._tools.list_tools()
        tools_for_api = self._format_tools_for_api(available_tools)

        # Phase 1: Planning (if enabled and task seems non-trivial)
        plan: str | None = None
        if self._config.enable_planning and self._seems_complex(user_message):
            plan_step = self._planner.plan(user_message, available_tools)
            trace.append(plan_step)
            plan = plan_step.content
            trace.total_llm_calls += 1

        # Phase 2: Main reasoning loop
        messages = self._build_initial_messages(user_message, context, plan)
        reflections: list[str] = []
        tools_used: list[str] = []
        retry_counts: dict[str, int] = {}

        for step_num in range(self._config.max_steps):
            # Check if reflection is needed
            if (
                self._config.enable_reflection
                and self._reflector.should_reflect(
                    trace.steps, self._config.reflection_threshold
                )
            ):
                reflection_step = self._reflector.reflect(
                    user_message, trace.format_for_context()
                )
                trace.append(reflection_step)
                reflections.append(reflection_step.content)
                trace.total_llm_calls += 1
                # Feed reflection back into conversation
                messages.append(AgentChatMessage(
                    role="assistant",
                    content=f"[Reflection] {reflection_step.content}",
                ))

            # Get LLM decision
            start_time = time.time()
            try:
                result = self._llm.chat(
                    messages,
                    tools=tools_for_api if tools_for_api else None,
                    temperature=self._config.temperature,
                    model=self._config.model,
                )
            except Exception as e:
                error_step = AgentStep(
                    kind=StepKind.ERROR,
                    error=f"LLM call failed: {e}",
                    duration_ms=(time.time() - start_time) * 1000,
                )
                trace.append(error_step)
                logger.error("LLM call failed at step %d: %s", step_num, e)
                break

            duration_ms = (time.time() - start_time) * 1000
            trace.total_llm_calls += 1
            trace.total_tokens += result.usage.get("total_tokens", 0)

            # Handle the response based on what the model decided
            if result.has_tool_calls:
                # Model wants to call a tool
                for tool_call in result.tool_calls or []:
                    tool_step, result_step = self._execute_tool(
                        tool_call.name,
                        tool_call.arguments,
                        tool_call.id,
                        retry_counts,
                    )
                    tool_step.duration_ms = duration_ms
                    trace.append(tool_step)
                    trace.append(result_step)

                    if tool_call.name not in tools_used:
                        tools_used.append(tool_call.name)

                    # Feed tool result back to conversation
                    messages.append(AgentChatMessage(
                        role="assistant",
                        content=None,
                        tool_calls=[
                            ToolCallMessage(
                                id=tool_call.id,
                                name=tool_call.name,
                                arguments=tool_call.arguments,
                            )
                        ],
                    ))
                    messages.append(AgentChatMessage(
                        role="tool",
                        content=result_step.content,
                        tool_call_id=tool_call.id,
                        name=tool_call.name,
                    ))

            elif result.content:
                # Model produced text — parse as structured action or treat as answer
                action = self._parse_action(result.content)

                if action["type"] == "think":
                    think_step = AgentStep(
                        kind=StepKind.THINK,
                        content=action["content"],
                        duration_ms=duration_ms,
                    )
                    trace.append(think_step)
                    messages.append(AgentChatMessage(
                        role="assistant", content=result.content
                    ))
                    # Prompt for next action
                    messages.append(AgentChatMessage(
                        role="user",
                        content="Continue. Choose your next action: think, tool_call, or answer.",
                    ))

                elif action["type"] == "tool_call":
                    # Model used JSON format to request a tool call
                    tool_name = action.get("tool_name", "")
                    arguments = action.get("arguments", {})
                    call_id = f"call_json_{step_num}"
                    tool_step, result_step = self._execute_tool(
                        tool_name, arguments, call_id, retry_counts
                    )
                    tool_step.duration_ms = duration_ms
                    trace.append(tool_step)
                    trace.append(result_step)
                    if tool_name not in tools_used:
                        tools_used.append(tool_name)
                    messages.append(AgentChatMessage(
                        role="assistant", content=result.content
                    ))
                    messages.append(AgentChatMessage(
                        role="user",
                        content=f"Tool result for {tool_name}:\n{result_step.content}\n\nContinue.",
                    ))

                elif action["type"] == "answer":
                    answer_step = AgentStep(
                        kind=StepKind.ANSWER,
                        content=action["content"],
                        duration_ms=duration_ms,
                    )
                    trace.append(answer_step)
                    trace.completed_at = datetime.now(UTC)
                    return AgentResponse(
                        answer=action["content"],
                        trace=trace,
                        plan=plan,
                        reflections=reflections,
                        tools_used=tools_used,
                        success=True,
                    )
                else:
                    # Treat unstructured text as final answer
                    answer_step = AgentStep(
                        kind=StepKind.ANSWER,
                        content=result.content,
                        duration_ms=duration_ms,
                    )
                    trace.append(answer_step)
                    trace.completed_at = datetime.now(UTC)
                    return AgentResponse(
                        answer=result.content,
                        trace=trace,
                        plan=plan,
                        reflections=reflections,
                        tools_used=tools_used,
                        success=True,
                    )
            else:
                # Empty response — shouldn't happen, but handle gracefully
                logger.warning("Empty LLM response at step %d", step_num)
                messages.append(AgentChatMessage(
                    role="user",
                    content="Your last response was empty. Please continue with think, tool_call, or answer.",
                ))

        # Exhausted max steps — produce best-effort answer
        trace.completed_at = datetime.now(UTC)
        fallback_answer = self._generate_fallback_answer(messages, trace)
        return AgentResponse(
            answer=fallback_answer,
            trace=trace,
            plan=plan,
            reflections=reflections,
            tools_used=tools_used,
            success=False,
        )

    def _build_initial_messages(
        self,
        user_message: str,
        context: str | None,
        plan: str | None,
    ) -> list[AgentChatMessage]:
        """Build the initial message sequence for the reasoning loop."""
        messages: list[AgentChatMessage] = [
            AgentChatMessage(role="system", content=AGENT_SYSTEM_PROMPT),
        ]

        # Add context if provided
        if context:
            messages.append(AgentChatMessage(
                role="system",
                content=f"## Additional Context\n{context}",
            ))

        # Add plan if generated
        if plan:
            messages.append(AgentChatMessage(
                role="system",
                content=f"## Your Plan\nFollow this plan, adjusting as needed:\n{plan}",
            ))

        messages.append(AgentChatMessage(role="user", content=user_message))
        return messages

    def _execute_tool(
        self,
        tool_name: str,
        arguments: dict[str, Any],
        call_id: str,
        retry_counts: dict[str, int],
    ) -> tuple[AgentStep, AgentStep]:
        """Execute a tool and return (call_step, result_step)."""
        # Track retries
        retry_key = f"{tool_name}:{json.dumps(arguments, sort_keys=True)}"
        retry_counts[retry_key] = retry_counts.get(retry_key, 0) + 1

        call_step = AgentStep(
            kind=StepKind.TOOL_CALL,
            tool_name=tool_name,
            tool_arguments=arguments,
            content=f"Calling {tool_name} with {arguments}",
        )

        if retry_counts[retry_key] > self._config.max_retries_per_tool:
            result_step = AgentStep(
                kind=StepKind.TOOL_RESULT,
                tool_name=tool_name,
                content=f"ERROR: Maximum retries ({self._config.max_retries_per_tool}) exceeded for {tool_name} with these arguments. Try different arguments or a different approach.",
                error="max retries exceeded",
            )
            return call_step, result_step

        try:
            result = self._tools.execute(tool_name, arguments)
            result_content = json.dumps(result, ensure_ascii=False, default=str)
            result_step = AgentStep(
                kind=StepKind.TOOL_RESULT,
                tool_name=tool_name,
                tool_result=result,
                content=result_content,
            )
        except Exception as e:
            logger.warning("Tool %s execution failed: %s", tool_name, e)
            result_step = AgentStep(
                kind=StepKind.TOOL_RESULT,
                tool_name=tool_name,
                content=f"ERROR: {e}",
                error=str(e),
            )

        return call_step, result_step

    def _parse_action(self, content: str) -> dict[str, Any]:
        """Parse the LLM's response to extract the action.

        Tries to parse as JSON first. If that fails, heuristically determines
        whether it's a think, tool_call, or answer.
        """
        content = content.strip()

        # Try to find JSON in the response (model sometimes adds prefix text)
        json_str = content
        # Handle markdown code blocks
        if "```" in json_str:
            lines = json_str.split("\n")
            json_lines = []
            in_block = False
            for line in lines:
                if line.startswith("```") and not in_block:
                    in_block = True
                    continue
                elif line.startswith("```") and in_block:
                    break
                elif in_block:
                    json_lines.append(line)
            if json_lines:
                json_str = "\n".join(json_lines)

        # Try to extract JSON from content that might have prefix/suffix text
        for candidate in [json_str, content]:
            # Find first { and try progressively shorter substrings
            start = candidate.find("{")
            if start == -1:
                continue
            # Try from first { to each } from the end
            end = len(candidate) - 1
            while end > start:
                if candidate[end] == "}":
                    try:
                        parsed = json.loads(candidate[start:end + 1])
                        if isinstance(parsed, dict) and "action" in parsed:
                            action_type = parsed["action"]
                            if action_type == "think":
                                return {"type": "think", "content": parsed.get("content", "")}
                            elif action_type == "tool_call":
                                return {
                                    "type": "tool_call",
                                    "tool_name": parsed.get("tool_name", ""),
                                    "arguments": parsed.get("arguments", {}),
                                }
                            elif action_type == "answer":
                                return {"type": "answer", "content": parsed.get("content", "")}
                    except (json.JSONDecodeError, KeyError, TypeError):
                        pass
                end -= 1

        # If not valid JSON action, treat as direct answer
        return {"type": "answer", "content": content}

    def _seems_complex(self, message: str) -> bool:
        """Heuristic: does this request seem complex enough to warrant planning?"""
        # Short messages or simple questions don't need planning
        if len(message) < 30:
            return False
        complexity_indicators = [
            "步骤", "计划", "分析", "评估", "比较", "设计", "实现",
            "step", "plan", "analyze", "evaluate", "compare", "design", "implement",
            "然后", "接着", "首先", "最后",
            "how to", "how do", "多个", "several", "multiple",
        ]
        return any(indicator in message.lower() for indicator in complexity_indicators)

    def _format_tools_for_api(self, tools: list[ToolDefinition]) -> list[dict[str, Any]]:
        """Format tools in OpenAI function-calling API format."""
        return [
            {
                "type": "function",
                "function": {
                    "name": tool.name,
                    "description": tool.description,
                    "parameters": tool.parameters,
                },
            }
            for tool in tools
        ]

    def _generate_fallback_answer(
        self, messages: list[AgentChatMessage], trace: AgentTrace
    ) -> str:
        """Generate a best-effort answer when max steps are exhausted."""
        messages_copy = list(messages)
        messages_copy.append(AgentChatMessage(
            role="user",
            content=(
                "You have reached the maximum number of reasoning steps. "
                "Based on everything you've learned so far, provide your best answer now. "
                "If you cannot fully answer, explain what you've found and what remains unclear."
            ),
        ))
        try:
            result = self._llm.chat(
                messages_copy, temperature=0.2, model=self._config.model
            )
            return result.content or "(Agent exhausted max steps without producing an answer)"
        except Exception as e:
            logger.error("Fallback answer generation failed: %s", e)
            # Compile what we learned from the trace
            tool_results = [
                s.content for s in trace.steps if s.kind == StepKind.TOOL_RESULT and not s.error
            ]
            if tool_results:
                return (
                    "I reached my reasoning step limit. Here's what I gathered:\n\n"
                    + "\n".join(f"- {r[:200]}" for r in tool_results[:5])
                )
            return "(Agent could not produce an answer within the step limit)"
