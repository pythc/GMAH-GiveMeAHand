"""End-to-end integration test: Agent with real tools and real LLM.

This test verifies the complete agent loop: planning, tool use, reflection,
and answer generation using the actual tool registry infrastructure.
"""

from __future__ import annotations

import os

import pytest
from pydantic import SecretStr

from agent_workflow.agent.llm_client import AgentLLMClient
from agent_workflow.agent.loop import AgentLoop
from agent_workflow.agent.models import AgentConfig, StepKind
from agent_workflow.agent.tool_bridge import RegistryToolCallback
from agent_workflow.integrations.grading.adapter import LocalGradingSystemAdapter
from agent_workflow.integrations.grading.tools import build_grading_executors
from agent_workflow.tools.executor import ToolExecutorRegistry
from agent_workflow.tools.loader import load_tool_specs
from agent_workflow.tools.registry import ToolRegistry

REAL_API_KEY = os.environ.get("MODEL_API_KEY", "")
SKIP_INTEGRATION = not REAL_API_KEY or REAL_API_KEY == "replace-with-local-secret"


def _build_agent_with_real_tools() -> AgentLoop:
    """Build a fully wired agent with real tool registry."""
    from pathlib import Path

    # Load real tool specs
    tools_path = Path("configs/tools.example.json")
    tool_specs = load_tool_specs(tools_path)
    tool_registry = ToolRegistry(tool_specs)
    executor_registry = ToolExecutorRegistry(tool_registry)

    # Register real grading executors
    grading_adapter = LocalGradingSystemAdapter()
    for tool_name, executor in build_grading_executors(grading_adapter).items():
        executor_registry.register(tool_name, executor)

    # Build LLM client
    llm = AgentLLMClient(
        base_url="https://ark.cn-beijing.volces.com/api/v3",
        model="doubao-seed-2-0-code-preview-260215",
        api_key=SecretStr(REAL_API_KEY),
        timeout_seconds=120,
    )

    # Bridge
    tool_callback = RegistryToolCallback(
        tool_registry=tool_registry,
        executor_registry=executor_registry,
    )

    config = AgentConfig(
        max_steps=12,
        enable_planning=True,
        enable_reflection=True,
        reflection_threshold=5,
        temperature=0.2,
    )
    return AgentLoop(llm=llm, tool_callback=tool_callback, config=config)


@pytest.mark.skipif(SKIP_INTEGRATION, reason="MODEL_API_KEY not set")
class TestAgentWithRealTools:
    """Integration tests using real tool registry + real LLM."""

    def test_fetch_assignment_flow(self):
        """Agent fetches assignment info using the real tool."""
        loop = _build_agent_with_real_tools()
        response = loop.run("请帮我获取 assignment-1 的作业信息。")

        print(f"\n=== RESULT ===")
        print(f"Success: {response.success}")
        print(f"Plan: {response.plan[:200] if response.plan else 'None'}")
        print(f"Tools used: {response.tools_used}")
        print(f"Steps: {len(response.trace.steps)}")
        print(f"LLM calls: {response.trace.total_llm_calls}")
        print(f"Answer: {response.answer[:400]}")

        assert response.success
        assert "fetch_assignment" in response.tools_used

    def test_multi_tool_flow(self):
        """Agent uses multiple tools to complete a complex task."""
        loop = _build_agent_with_real_tools()
        response = loop.run(
            "我需要评审一个学生的作业。请先获取 assignment-1 的信息，"
            "然后获取评分标准 v1，最后获取 submission-1 的提交内容。"
            "完成后给我一个综合摘要。"
        )

        print(f"\n=== MULTI-TOOL RESULT ===")
        print(f"Success: {response.success}")
        print(f"Plan: {response.plan[:300] if response.plan else 'None'}")
        print(f"Tools used: {response.tools_used}")
        print(f"Steps: {len(response.trace.steps)}")
        print(f"Answer: {response.answer[:500]}")

        # Print each step
        for step in response.trace.steps:
            print(f"  [{step.kind.value}] {step.content[:100]}")

        assert response.success
        # Should have used multiple tools
        assert len(response.tools_used) >= 2

    def test_error_recovery(self):
        """Agent handles tool errors gracefully."""
        loop = _build_agent_with_real_tools()
        # Ask for a non-existent tool — the agent should recognize the error
        response = loop.run("请使用 nonexistent_tool 来查询数据。")

        print(f"\n=== ERROR RECOVERY ===")
        print(f"Success: {response.success}")
        print(f"Answer: {response.answer[:300]}")

        assert response.success
        # Agent should explain it can't use the requested tool

    def test_autonomous_planning_and_execution(self):
        """Full autonomous loop: plan, execute, reflect, answer."""
        loop = _build_agent_with_real_tools()
        response = loop.run(
            "请帮我完成以下任务：\n"
            "1. 获取 assignment-1 的作业要求\n"
            "2. 获取该作业的 v1 版本评分标准\n"
            "3. 获取 submission-1 的学生提交\n"
            "4. 基于评分标准，给出初步评价建议\n"
            "请逐步执行并给出最终分析报告。"
        )

        print(f"\n=== FULL AUTONOMOUS LOOP ===")
        print(f"Success: {response.success}")
        print(f"Plan: {response.plan[:300] if response.plan else 'None'}")
        print(f"Tools used: {response.tools_used}")
        print(f"Reflections: {len(response.reflections)}")
        print(f"Steps: {len(response.trace.steps)}")
        print(f"LLM calls: {response.trace.total_llm_calls}")
        print(f"Tokens: {response.trace.total_tokens}")
        print(f"\n--- Answer ---")
        print(response.answer[:800])
        print(f"\n--- Trace ---")
        for step in response.trace.steps:
            kind = step.kind.value.upper()
            summary = step.content[:80] if step.content else ""
            print(f"  [{kind}] {step.tool_name or ''} {summary}")

        assert response.success
        assert len(response.tools_used) >= 3
