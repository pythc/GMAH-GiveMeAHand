"""Function-tool bindings for grading-system adapters."""

from typing import Any

from agent_workflow.integrations.grading.adapter import GradingSystemAdapter
from agent_workflow.tools.executor import CallableToolExecutor, ToolExecutor


def _as_str(arguments: dict[str, Any], key: str) -> str:
    value = arguments[key]
    if not isinstance(value, str):
        raise TypeError(f"{key} must be a string")
    return value


def _as_float(arguments: dict[str, Any], key: str) -> float:
    value = arguments[key]
    if not isinstance(value, int | float):
        raise TypeError(f"{key} must be a number")
    return float(value)


def build_grading_executors(adapter: GradingSystemAdapter) -> dict[str, ToolExecutor]:
    """Bind grading adapter methods to tool executors."""

    def fetch_assignment(arguments: dict[str, Any]) -> dict[str, Any]:
        assignment = adapter.fetch_assignment(_as_str(arguments, "assignment_id"))
        return assignment.model_dump(mode="json")

    def fetch_rubric(arguments: dict[str, Any]) -> dict[str, Any]:
        rubric = adapter.fetch_rubric(
            _as_str(arguments, "assignment_id"),
            _as_str(arguments, "rubric_version"),
        )
        return rubric.model_dump(mode="json")

    def fetch_submission(arguments: dict[str, Any]) -> dict[str, Any]:
        submission = adapter.fetch_submission(_as_str(arguments, "submission_id"))
        return submission.model_dump(mode="json")

    def save_feedback_draft(arguments: dict[str, Any]) -> dict[str, Any]:
        draft = adapter.save_feedback_draft(
            submission_id=_as_str(arguments, "submission_id"),
            draft_revision=_as_str(arguments, "draft_revision"),
            feedback_markdown=_as_str(arguments, "feedback_markdown"),
        )
        return draft.model_dump(mode="json")

    def publish_grade(arguments: dict[str, Any]) -> dict[str, Any]:
        grade = adapter.publish_grade(
            submission_id=_as_str(arguments, "submission_id"),
            rubric_version=_as_str(arguments, "rubric_version"),
            score=_as_float(arguments, "score"),
            feedback_markdown=_as_str(arguments, "feedback_markdown"),
        )
        return grade.model_dump(mode="json")

    return {
        "fetch_assignment": CallableToolExecutor("fetch_assignment", fetch_assignment),
        "fetch_rubric": CallableToolExecutor("fetch_rubric", fetch_rubric),
        "fetch_submission": CallableToolExecutor("fetch_submission", fetch_submission),
        "save_feedback_draft": CallableToolExecutor("save_feedback_draft", save_feedback_draft),
        "publish_grade": CallableToolExecutor("publish_grade", publish_grade),
    }
