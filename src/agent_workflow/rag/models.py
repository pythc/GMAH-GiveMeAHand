"""Data models for multimodal retrieval."""

from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field


class Modality(StrEnum):
    TEXT = "text"
    IMAGE = "image"
    PAGE = "page"
    AUDIO_TRANSCRIPT = "audio_transcript"
    TABLE = "table"


class IngestPage(BaseModel):
    page_number: int = Field(ge=1)
    artifact_uri: str
    text: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class IngestDocument(BaseModel):
    source_id: str
    text: str | None = None
    tenant_id: str | None = None
    pages: list[IngestPage] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


class IngestChunk(BaseModel):
    chunk_id: str
    source_id: str
    modality: Modality
    content: str | None = None
    artifact_uri: str | None = None
    tenant_id: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class IngestResult(BaseModel):
    source_ids: list[str]
    text_chunks: int = 0
    visual_chunks: int = 0


class RetrievalQuery(BaseModel):
    query: str
    tenant_id: str | None = None
    filters: dict[str, Any] = Field(default_factory=dict)
    text_top_k: int = Field(default=20, ge=1, le=100)
    visual_top_k: int = Field(default=10, ge=0, le=100)


class RetrievalEvidence(BaseModel):
    source_id: str
    modality: Modality
    score: float = Field(ge=0)
    content: str | None = None
    artifact_uri: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class RetrievalResult(BaseModel):
    query: RetrievalQuery
    evidence: list[RetrievalEvidence] = Field(default_factory=list)
