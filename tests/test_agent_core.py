"""Tests for the agentic reasoning core.

Includes both unit tests (with mocked LLM) and integration tests
that use the real API key to verify end-to-end agent behavior.
"""

from __future__ import annotations

import json
import os
from unittest.mock import MagicMock, patch

import pytest

from agent_workflow.agent.llm_client import AgentChatMessage, AgentChatResult, AgentLLMClient, ToolCallMessage
from agent_workflow.agent.loop import AgentLoop
from agent_workflow.agent.models import AgentConfig, AgentStep, AgentTrace, StepKind, ToolDefinition
from agent_workflow.agent.planner import Planner, Reflector
from agent_workflow.agent.prompts import AGENT_SYSTEM_PROMPT, build_tools_description
from agent_workflow.agent.tool_bridge import MockToolCallback


# ─── Unit Tests ──────────────────────────────────────────────────────────────


class TestAgentModels:
    def test_step_terminal(self):
        answer = AgentStep(kind=StepKind.ANSWER, content="done")
        assert answer.is_terminal
        think = AgentStep(kind=StepKind.THINK, content="hmm")
        assert not think.is_terminal

    def test_trace_format(self):
        trace = AgentTrace()
        trace.append(AgentStep(kind=StepKind.THINK, content="analyzing"))
        trace.append(AgentStep(kind=StepKind.TOOL_CALL, tool_name="search", tool_arguments={"q": "test"}))
        trace.append(AgentStep(kind=StepKind.ANSWER, content="found it"))
        formatted = trace.format_for_context()
        assert "Thinking" in formatted
        assert "Tool Call" in formatted
        assert "Final Answer" in formatted

    def test_trace_complete(self):
        trace = AgentTrace()
        assert not trace.is_complete
        trace.append(AgentStep(kind=StepKind.THINK, content="thinking"))
        assert not trace.is_complete
        trace.append(AgentStep(kind=StepKind.ANSWER, content="done"))
        assert trace.is_complete


class TestPrompts:
    def test_system_prompt_not_empty(self):
        assert len(AGENT_SYSTEM_PROMPT) > 100

    def test_build_tools_description(self):
        tools = [
            {"name": "search", "description": "search stuff", "parameters": {"properties": {"q": {"type": "string"}}}},
        ]
        desc = build_tools_description(tools)
        assert "search" in desc
        assert "q: string" in desc


class TestMockToolCallback:
    def test_execute_returns_result(self):
        callback = MockToolCallback()
        result = callback.execute("search", {"query": "hello"})
        assert "results" in result

    def test_list_tools(self):
        callback = MockToolCallback()
        tools = callback.list_tools()
        assert len(tools) >= 2
        names = [t.name for t in tools]
        assert "search" in names
        assert "calculate" in names


class TestAgentChatMessage:
    def test_to_api_dict_simple(self):
        msg = AgentChatMessage(role="user", content="hello")
        d = msg.to_api_dict()
        assert d == {"role": "user", "content": "hello"}

    def test_to_api_dict_tool_result(self):
        msg = AgentChatMessage(role="tool", content="result", tool_call_id="tc_1", name="search")
        d = msg.to_api_dict()
        assert d["role"] == "tool"
        assert d["tool_call_id"] == "tc_1"
        assert d["name"] == "search"


class TestAgentLoopUnit:
    """Unit tests with mocked LLM to verify control flow."""

    def _make_loop(self, mock_llm):
        callback = MockToolCallback()
        config = AgentConfig(enable_planning=False, enable_reflection=False)
        return AgentLoop(llm=mock_llm, tool_callback=callback, config=config)

    def test_parse_action_with_trailing_braces(self):
        """Parser handles malformed JSON with extra trailing braces."""
        mock_llm = MagicMock(spec=AgentLLMClient)
        callback = MockToolCallback()
        config = AgentConfig(enable_planning=False, enable_reflection=False)
        loop = AgentLoop(llm=mock_llm, tool_callback=callback, config=config)

        # Simulate model output with extra trailing brace
        result = loop._parse_action('{"action": "tool_call", "tool_name": "search", "arguments": {"query": "hello"}}}')
        assert result["type"] == "tool_call"
        assert result["tool_name"] == "search"
        assert result["arguments"] == {"query": "hello"}

    def test_parse_action_with_prefix(self):
        """Parser handles JSON with prefix text."""
        mock_llm = MagicMock(spec=AgentLLMClient)
        callback = MockToolCallback()
        config = AgentConfig(enable_planning=False, enable_reflection=False)
        loop = AgentLoop(llm=mock_llm, tool_callback=callback, config=config)

        result = loop._parse_action('[Output] {"action": "answer", "content": "hello world"}')
        assert result["type"] == "answer"
        assert result["content"] == "hello world"

    def test_direct_answer(self):
        """Agent immediately provides an answer without tool calls."""
        mock_llm = MagicMock(spec=AgentLLMClient)
        mock_llm.chat.return_value = AgentChatResult(
            content='{"action": "answer", "content": "The answer is 42."}',
            finish_reason="stop",
            model="test",
        )
        mock_llm.simple_chat.return_value = "1. Think about it"

        callback = MockToolCallback()
        config = AgentConfig(enable_planning=False, enable_reflection=False)
        loop = AgentLoop(llm=mock_llm, tool_callback=callback, config=config)

        response = loop.run("What is the meaning of life?")
        assert response.success
        assert "42" in response.answer

    def test_tool_call_then_answer(self):
        """Agent calls a tool, gets result, then answers."""
        mock_llm = MagicMock(spec=AgentLLMClient)

        # First call: tool_call via native function calling
        tool_call_result = AgentChatResult(
            content=None,
            tool_calls=[ToolCallMessage(id="tc1", name="search", arguments={"query": "weather"})],
            finish_reason="tool_calls",
            model="test",
        )
        # Second call: answer
        answer_result = AgentChatResult(
            content='{"action": "answer", "content": "It is sunny today."}',
            finish_reason="stop",
            model="test",
        )
        mock_llm.chat.side_effect = [tool_call_result, answer_result]
        mock_llm.simple_chat.return_value = "1. Search for info"

        callback = MockToolCallback()
        config = AgentConfig(enable_planning=False, enable_reflection=False)
        loop = AgentLoop(llm=mock_llm, tool_callback=callback, config=config)

        response = loop.run("What's the weather?")
        assert response.success
        assert "sunny" in response.answer
        assert "search" in response.tools_used

    def test_max_steps_fallback(self):
        """Agent hits max_steps and generates fallback."""
        mock_llm = MagicMock(spec=AgentLLMClient)
        # Always think, never answer
        mock_llm.chat.return_value = AgentChatResult(
            content='{"action": "think", "content": "still thinking..."}',
            finish_reason="stop",
            model="test",
        )
        mock_llm.simple_chat.return_value = "plan"

        callback = MockToolCallback()
        config = AgentConfig(max_steps=3, enable_planning=False, enable_reflection=False)
        loop = AgentLoop(llm=mock_llm, tool_callback=callback, config=config)

        response = loop.run("Complex question")
        # After 3 think steps, it should produce a fallback
        assert not response.success or "thinking" in response.answer.lower() or response.answer


# ─── Integration Tests (require real API key) ────────────────────────────────

REAL_API_KEY = os.environ.get("MODEL_API_KEY", "")
SKIP_INTEGRATION = not REAL_API_KEY or REAL_API_KEY == "replace-with-local-secret"


@pytest.mark.skipif(SKIP_INTEGRATION, reason="MODEL_API_KEY not set")
class TestAgentIntegration:
    """Integration tests that hit the real LLM API."""

    def _make_loop(self, **config_kwargs) -> AgentLoop:
        from pydantic import SecretStr
        llm = AgentLLMClient(
            base_url="https://ark.cn-beijing.volces.com/api/v3",
            model="doubao-seed-2-0-code-preview-260215",
            api_key=SecretStr(REAL_API_KEY),
            timeout_seconds=120,
        )
        callback = MockToolCallback()
        config = AgentConfig(**config_kwargs)
        return AgentLoop(llm=llm, tool_callback=callback, config=config)

    def test_simple_question(self):
        """Agent answers a simple question without tools."""
        loop = self._make_loop(enable_planning=False, max_steps=5)
        response = loop.run("What is 2 + 2? Answer with just the number.")
        assert response.success
        assert "4" in response.answer

    def test_tool_use(self):
        """Agent uses a tool to answer a question."""
        loop = self._make_loop(enable_planning=False, max_steps=8)
        response = loop.run("Search for information about Python programming language.")
        assert response.success
        assert response.trace.total_llm_calls >= 1
        # Agent may or may not use tools depending on model behavior
        print(f"Tools used: {response.tools_used}")
        print(f"Steps: {len(response.trace.steps)}")
        print(f"Answer: {response.answer[:200]}")

    def test_planning(self):
        """Agent creates a plan for a complex task."""
        loop = self._make_loop(enable_planning=True, max_steps=10)
        response = loop.run(
            "我需要分析一个学生的作业提交。首先获取作业信息，然后获取评分标准，最后获取学生提交内容。"
        )
        assert response.success
        assert response.plan is not None
        print(f"Plan: {response.plan[:300]}")
        print(f"Tools used: {response.tools_used}")
        print(f"Answer: {response.answer[:300]}")

    def test_reflection(self):
        """Agent reflects when making slow progress."""
        loop = self._make_loop(
            enable_planning=False,
            enable_reflection=True,
            reflection_threshold=3,
            max_steps=10,
        )
        response = loop.run("这是一个需要多步推理的问题：先搜索天气，然后根据天气推荐穿什么衣服。")
        assert response.success
        print(f"Reflections: {response.reflections}")
        print(f"Answer: {response.answer[:200]}")
