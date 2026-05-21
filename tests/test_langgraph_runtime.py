from pathlib import Path

from agent_workflow.api.dependencies import (
    build_default_langgraph_runtime,
    build_default_orchestrator,
)
from agent_workflow.config import AppSettings
from agent_workflow.orchestrator.models import RunSessionRequest
from agent_workflow.tools.schemas import ToolCallRequest


def test_langgraph_runtime_executes_session_turn() -> None:
    settings = AppSettings(tools_config_path=Path("configs/tools.example.json"))
    orchestrator = build_default_orchestrator(settings)
    runtime = build_default_langgraph_runtime(orchestrator, settings)
    assert runtime is not None

    result = runtime.run(
        RunSessionRequest(
            user_id="teacher-1",
            tool_call=ToolCallRequest(
                tool_name="fetch_submission",
                arguments={"submission_id": "submission-1"},
                call_id="langgraph-call-1",
            ),
        )
    )

    assert result.tool_result is not None
    assert result.tool_result.status == "accepted"
