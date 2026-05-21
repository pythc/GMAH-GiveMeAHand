"""Grading-system adapter boundary and local MVP implementation."""

from typing import Protocol
from uuid import uuid4

from agent_workflow.integrations.grading.models import (
    Assignment,
    FeedbackDraft,
    PublishedGrade,
    Rubric,
    RubricCriterion,
    Submission,
)


class GradingAdapterError(ValueError):
    """Raised when grading data cannot be found or written."""


class GradingSystemAdapter(Protocol):
    """Business API boundary for grading systems."""

    def fetch_assignment(self, assignment_id: str) -> Assignment:
        """Fetch assignment metadata."""

    def fetch_rubric(self, assignment_id: str, rubric_version: str) -> Rubric:
        """Fetch rubric criteria."""

    def fetch_submission(self, submission_id: str) -> Submission:
        """Fetch a student submission."""

    def save_feedback_draft(
        self,
        *,
        submission_id: str,
        draft_revision: str,
        feedback_markdown: str,
    ) -> FeedbackDraft:
        """Save a non-public feedback draft."""

    def publish_grade(
        self,
        *,
        submission_id: str,
        rubric_version: str,
        score: float,
        feedback_markdown: str,
    ) -> PublishedGrade:
        """Publish a grade after approval."""


class LocalGradingSystemAdapter:
    """Deterministic in-memory grading adapter for MVP demos and tests."""

    def __init__(self) -> None:
        self._assignments: dict[str, Assignment] = {
            "assignment-1": Assignment(
                assignment_id="assignment-1",
                course_id="course-ml-101",
                title="多模态 RAG 方案评审",
                rubric_version="v1",
            )
        }
        self._rubrics: dict[tuple[str, str], Rubric] = {
            ("assignment-1", "v1"): Rubric(
                rubric_version="v1",
                assignment_id="assignment-1",
                criteria=[
                    RubricCriterion(
                        name="architecture",
                        max_score=40,
                        description="架构分层清晰，工具、RAG、记忆边界明确。",
                    ),
                    RubricCriterion(
                        name="safety",
                        max_score=30,
                        description="包含审批、审计、幂等与权限控制。",
                    ),
                    RubricCriterion(
                        name="evaluation",
                        max_score=30,
                        description="包含检索、回答与摘要质量评估指标。",
                    ),
                ],
            )
        }
        self._submissions: dict[str, Submission] = {
            "submission-1": Submission(
                submission_id="submission-1",
                assignment_id="assignment-1",
                student_id="student-1",
                content="本文提出基于 Qdrant 与 BGE-M3 的文本检索方案。",
            )
        }
        self._drafts: dict[tuple[str, str], FeedbackDraft] = {}
        self._published: dict[tuple[str, str], PublishedGrade] = {}

    def fetch_assignment(self, assignment_id: str) -> Assignment:
        assignment = self._assignments.get(assignment_id)
        if assignment is None:
            raise GradingAdapterError(f"unknown assignment: {assignment_id}")
        return assignment.model_copy(deep=True)

    def fetch_rubric(self, assignment_id: str, rubric_version: str) -> Rubric:
        rubric = self._rubrics.get((assignment_id, rubric_version))
        if rubric is None:
            raise GradingAdapterError(f"unknown rubric: {assignment_id}/{rubric_version}")
        return rubric.model_copy(deep=True)

    def fetch_submission(self, submission_id: str) -> Submission:
        submission = self._submissions.get(submission_id)
        if submission is None:
            raise GradingAdapterError(f"unknown submission: {submission_id}")
        return submission.model_copy(deep=True)

    def save_feedback_draft(
        self,
        *,
        submission_id: str,
        draft_revision: str,
        feedback_markdown: str,
    ) -> FeedbackDraft:
        self.fetch_submission(submission_id)
        key = (submission_id, draft_revision)
        draft = FeedbackDraft(
            draft_id=f"draft_{uuid4().hex}",
            submission_id=submission_id,
            draft_revision=draft_revision,
            feedback_markdown=feedback_markdown,
        )
        self._drafts[key] = draft
        return draft.model_copy(deep=True)

    def publish_grade(
        self,
        *,
        submission_id: str,
        rubric_version: str,
        score: float,
        feedback_markdown: str,
    ) -> PublishedGrade:
        submission = self.fetch_submission(submission_id)
        self.fetch_rubric(submission.assignment_id, rubric_version)
        key = (submission_id, rubric_version)
        published = PublishedGrade(
            publish_id=f"grade_{uuid4().hex}",
            submission_id=submission_id,
            rubric_version=rubric_version,
            score=score,
            feedback_markdown=feedback_markdown,
        )
        self._published[key] = published
        return published.model_copy(deep=True)
