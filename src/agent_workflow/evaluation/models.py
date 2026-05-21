"""Models for evaluating research project artifacts."""

from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field, model_validator


class ArtifactKind(StrEnum):
    REPORT = "report"
    PAPER = "paper"
    PRESENTATION = "presentation"
    VIDEO = "video"
    CODE_REPOSITORY = "code_repository"
    DATASET = "dataset"
    EXPERIMENT_LOG = "experiment_log"
    OTHER = "other"


class ArtifactInput(BaseModel):
    artifact_id: str = Field(min_length=1)
    kind: ArtifactKind
    title: str = Field(min_length=1)
    uri: str | None = None
    text: str | None = None
    transcript: str | None = None
    repository_summary: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def require_reviewable_content(self) -> "ArtifactInput":
        if not any([self.uri, self.text, self.transcript, self.repository_summary, self.metadata]):
            raise ValueError(
                "artifact requires uri, text, transcript, repository_summary, or metadata"
            )
        return self


class RubricCriterion(BaseModel):
    criterion_id: str = Field(min_length=1)
    name: str = Field(min_length=1)
    description: str
    weight: float = Field(gt=0, le=1)


class EvaluationRubric(BaseModel):
    name: str
    criteria: list[RubricCriterion] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_weights(self) -> "EvaluationRubric":
        total = sum(criterion.weight for criterion in self.criteria)
        if not 0.99 <= total <= 1.01:
            raise ValueError("rubric weights must sum to 1.0")
        return self


class ProjectEvaluationRequest(BaseModel):
    topic_title: str = Field(min_length=1)
    topic_goal: str = Field(min_length=1)
    artifacts: list[ArtifactInput] = Field(min_length=1)
    rubric: EvaluationRubric | None = None


class ArtifactAssessment(BaseModel):
    artifact_id: str
    kind: ArtifactKind
    title: str
    word_count: int
    evidence_signals: list[str] = Field(default_factory=list)
    missing_signals: list[str] = Field(default_factory=list)


class CriterionAssessment(BaseModel):
    criterion_id: str
    name: str
    score: float = Field(ge=0, le=100)
    weight: float
    evidence: list[str] = Field(default_factory=list)
    issues: list[str] = Field(default_factory=list)
    suggestions: list[str] = Field(default_factory=list)


class ProjectEvaluationResult(BaseModel):
    topic_title: str
    overall_score: float = Field(ge=0, le=100)
    summary: str
    coverage: dict[str, bool]
    artifact_assessments: list[ArtifactAssessment]
    criterion_assessments: list[CriterionAssessment]
    strengths: list[str] = Field(default_factory=list)
    weaknesses: list[str] = Field(default_factory=list)
    recommendations: list[str] = Field(default_factory=list)
    next_steps: list[str] = Field(default_factory=list)
