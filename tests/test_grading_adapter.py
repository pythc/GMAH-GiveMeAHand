import pytest

from agent_workflow.integrations.grading.adapter import (
    GradingAdapterError,
    LocalGradingSystemAdapter,
)
from agent_workflow.integrations.grading.tools import build_grading_executors
from agent_workflow.tools.schemas import ToolCallRequest


def test_local_grading_adapter_reads_seed_data() -> None:
    adapter = LocalGradingSystemAdapter()
    assignment = adapter.fetch_assignment("assignment-1")
    submission = adapter.fetch_submission("submission-1")
    rubric = adapter.fetch_rubric(assignment.assignment_id, assignment.rubric_version)

    assert assignment.course_id == "course-ml-101"
    assert submission.assignment_id == assignment.assignment_id
    assert rubric.criteria


def test_local_grading_adapter_writes_draft_and_grade() -> None:
    adapter = LocalGradingSystemAdapter()
    draft = adapter.save_feedback_draft(
        submission_id="submission-1",
        draft_revision="r1",
        feedback_markdown="反馈草稿",
    )
    grade = adapter.publish_grade(
        submission_id="submission-1",
        rubric_version="v1",
        score=88,
        feedback_markdown="正式反馈",
    )

    assert draft.submission_id == "submission-1"
    assert grade.score == 88


def test_local_grading_adapter_rejects_unknown_records() -> None:
    adapter = LocalGradingSystemAdapter()
    with pytest.raises(GradingAdapterError):
        adapter.fetch_assignment("missing")
    with pytest.raises(GradingAdapterError):
        adapter.fetch_submission("missing")
    with pytest.raises(GradingAdapterError):
        adapter.fetch_rubric("assignment-1", "missing")


def test_grading_tool_executors_fetch_and_validate_argument_types() -> None:
    executors = build_grading_executors(LocalGradingSystemAdapter())
    assignment = executors["fetch_assignment"].execute(
        ToolCallRequest(tool_name="fetch_assignment", arguments={"assignment_id": "assignment-1"})
    )
    rubric = executors["fetch_rubric"].execute(
        ToolCallRequest(
            tool_name="fetch_rubric",
            arguments={"assignment_id": "assignment-1", "rubric_version": "v1"},
        )
    )
    failed = executors["publish_grade"].execute(
        ToolCallRequest(
            tool_name="publish_grade",
            arguments={
                "submission_id": "submission-1",
                "rubric_version": "v1",
                "score": "bad",
                "feedback_markdown": "反馈",
            },
        )
    )

    assert assignment.accepted is True
    assert rubric.output["criteria"]
    assert failed.accepted is False
    assert "score must be a number" in (failed.error or "")
