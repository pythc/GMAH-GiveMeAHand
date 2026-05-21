"""RAG configuration loader."""

from pathlib import Path

import yaml
from pydantic import BaseModel, ConfigDict, Field


class TextCollectionConfig(BaseModel):
    model_config = ConfigDict(extra="allow")

    collection_name: str = "agent_text"
    vector_name: str = "dense"
    embedding_model: str = "hash-local"
    chunk_size_tokens: int = Field(default=800, ge=1)
    chunk_overlap_tokens: int = Field(default=120, ge=0)


class VisualCollectionConfig(BaseModel):
    model_config = ConfigDict(extra="allow")

    collection_name: str = "agent_visual"
    vector_name: str = "visual"
    embedding_model: str = "hash-local-visual"
    granularity: str = "page"


class RetrievalConfig(BaseModel):
    model_config = ConfigDict(extra="allow")

    text_top_k: int = Field(default=20, ge=1)
    visual_top_k: int = Field(default=10, ge=0)
    fused_top_k: int = Field(default=8, ge=1)
    reranker: str | None = None
    require_citations: bool = True


class RagCollectionsConfig(BaseModel):
    text: TextCollectionConfig = Field(default_factory=TextCollectionConfig)
    page_visual: VisualCollectionConfig = Field(default_factory=VisualCollectionConfig)


class RagConfig(BaseModel):
    model_config = ConfigDict(extra="allow")

    collections: RagCollectionsConfig = Field(default_factory=RagCollectionsConfig)
    retrieval: RetrievalConfig = Field(default_factory=RetrievalConfig)


def load_rag_config(path: Path) -> RagConfig:
    with path.open(encoding="utf-8") as file:
        payload = yaml.safe_load(file) or {}
    return RagConfig.model_validate(payload)
