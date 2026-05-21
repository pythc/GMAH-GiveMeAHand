"""Domain models for grading-system integration."""

from datetime import UTC, datetime

from pydantic import BaseModel, Field


class Assignment(BaseModel):
    assignment_id: str
    course_id: str
    title: str
    rubric_version: str


class RubricCriterion(BaseModel):
    name: str
    max_score: float
    description: str


class Rubric(BaseModel):
    rubric_version: str
    assignment_id: str
    criteria: list[RubricCriterion] = Field(default_factory=list)


class Submission(BaseModel):
    submission_id: str
    assignment_id: str
    student_id: str
    content: str
    submitted_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class FeedbackDraft(BaseModel):
    draft_id: str
    submission_id: str
    draft_revision: str
    feedback_markdown: str
    saved_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class PublishedGrade(BaseModel):
    publish_id: str
    submission_id: str
    rubric_version: str
    score: float
    feedback_markdown: str
    published_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
