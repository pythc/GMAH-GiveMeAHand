"""Memory data models."""

from datetime import UTC, datetime
from enum import StrEnum

from pydantic import BaseModel, Field, model_validator


class MemoryKind(StrEnum):
    WORKING = "working"
    SUMMARY = "summary"
    EPISODIC = "episodic"
    SEMANTIC = "semantic"
    IDENTITY = "identity"


class MemoryRecord(BaseModel):
    id: str
    kind: MemoryKind
    content: str
    source: str
    scope: str
    confidence: float = Field(default=1.0, ge=0, le=1)
    sensitive: bool = False
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    tags: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def require_source_for_long_term_memory(self) -> "MemoryRecord":
        long_term_kinds = {MemoryKind.EPISODIC, MemoryKind.SEMANTIC, MemoryKind.IDENTITY}
        if self.kind in long_term_kinds and not self.source:
            raise ValueError("long-term memory requires a source")
        return self


class SessionSummary(BaseModel):
    thread_id: str
    persistent_facts: list[str] = Field(default_factory=list)
    session_goals: list[str] = Field(default_factory=list)
    open_tasks: list[str] = Field(default_factory=list)
    decisions_made: list[str] = Field(default_factory=list)
    unresolved_questions: list[str] = Field(default_factory=list)
    referenced_artifacts: list[str] = Field(default_factory=list)
    tool_side_effects: list[str] = Field(default_factory=list)
    sensitive_data_to_redact: list[str] = Field(default_factory=list)
