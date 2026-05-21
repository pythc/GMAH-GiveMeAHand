from pathlib import Path

from agent_workflow.api.dependencies import build_default_orchestrator
from agent_workflow.config import AppSettings
from agent_workflow.orchestrator.models import RunSessionRequest
from agent_workflow.orchestrator.service import SessionOrchestrator
from agent_workflow.orchestrator.state import ApprovalStatus
from agent_workflow.tools.schemas import ToolCallRequest


def make_orchestrator() -> SessionOrchestrator:
    settings = AppSettings(tools_config_path=Path("configs/tools.example.json"))
    return build_default_orchestrator(settings)


def test_session_orchestrator_executes_medium_risk_draft_tool() -> None:
    orchestrator = make_orchestrator()
    result = orchestrator.run(
        RunSessionRequest(
            user_id="teacher-1",
            message="保存反馈草稿",
            tool_call=ToolCallRequest(
                tool_name="save_feedback_draft",
                arguments={
                    "submission_id": "submission-1",
                    "draft_revision": "r1",
                    "feedback_markdown": "结构清晰，建议补充评估指标。",
                },
                call_id="call-draft-1",
            ),
        )
    )

    assert result.approval_required is False
    assert result.tool_result is not None
    assert result.tool_result.status == "accepted"
    assert result.state.messages[0].content == "保存反馈草稿"


def test_session_orchestrator_pauses_high_risk_publish_until_approval() -> None:
    orchestrator = make_orchestrator()
    result = orchestrator.run(
        RunSessionRequest(
            user_id="teacher-1",
            tool_call=ToolCallRequest(
                tool_name="publish_grade",
                arguments={
                    "submission_id": "submission-1",
                    "rubric_version": "v1",
                    "score": 90,
                    "feedback_markdown": "可发布反馈。",
                },
                call_id="call-grade-1",
            ),
        )
    )

    assert result.approval_required is True
    assert result.pending_approval is not None
    assert result.tool_result is None
    assert result.state.approval_status is ApprovalStatus.PENDING

    decided = orchestrator.decide_approval(
        result.pending_approval.approval_id,
        approved_by="reviewer-1",
        approved=True,
        reason="人工复核通过",
    )
    assert decided.tool_result is not None
    assert decided.tool_result.status == "accepted"
    assert decided.state.approval_status is ApprovalStatus.APPROVED


def test_session_orchestrator_replays_idempotent_draft_result() -> None:
    orchestrator = make_orchestrator()
    request = RunSessionRequest(
        user_id="teacher-1",
        tool_call=ToolCallRequest(
            tool_name="save_feedback_draft",
            arguments={
                "submission_id": "submission-1",
                "draft_revision": "r2",
                "feedback_markdown": "同一修订版本只保存一次。",
            },
            call_id="call-draft-2",
        ),
    )

    first = orchestrator.run(request)
    second = orchestrator.run(request)

    assert first.idempotent_replay is False
    assert second.idempotent_replay is True
    assert second.tool_result is not None
    assert second.tool_result.output["idempotent_replay"] is True
