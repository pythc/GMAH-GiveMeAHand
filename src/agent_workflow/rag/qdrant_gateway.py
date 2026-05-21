"""Qdrant-backed multimodal RAG gateway."""

from __future__ import annotations

import hashlib
import importlib
from typing import Any
from uuid import UUID

from agent_workflow.rag.config import RagConfig
from agent_workflow.rag.embeddings import EmbeddingModel, HashEmbeddingModel, Reranker
from agent_workflow.rag.ingestion import chunk_documents
from agent_workflow.rag.models import (
    IngestChunk,
    IngestDocument,
    IngestResult,
    Modality,
    RetrievalEvidence,
    RetrievalQuery,
    RetrievalResult,
)


class QdrantGatewayError(RuntimeError):
    """Raised when Qdrant cannot ingest or retrieve documents."""


class QdrantRagGateway:
    """Qdrant-backed text + page visual retrieval gateway.

    The embedding model is injected. By default this uses a deterministic local
    embedding for reproducible development; production can inject BGE-M3 and
    ColPali/ColQwen embedding adapters while keeping Qdrant as the index layer.
    """

    def __init__(
        self,
        *,
        url: str,
        config: RagConfig | None = None,
        api_key: str | None = None,
        embedding_model: EmbeddingModel | None = None,
        reranker: Reranker | None = None,
        dimension: int = 64,
        text_collection: str | None = None,
        visual_collection: str | None = None,
    ) -> None:
        self.config = config or RagConfig()
        self.embedding_model = embedding_model or HashEmbeddingModel(dimension)
        self._reranker = reranker
        self.text_collection = text_collection or self.config.collections.text.collection_name
        self.visual_collection = (
            visual_collection or self.config.collections.page_visual.collection_name
        )
        self._qdrant_client_module = importlib.import_module("qdrant_client")
        self._models_module = importlib.import_module("qdrant_client.models")
        self._client: Any = self._qdrant_client_module.QdrantClient(url=url, api_key=api_key)
        self._collections_ready = False

    def ingest_documents(self, documents: list[IngestDocument]) -> IngestResult:
        self._ensure_collections()
        chunks = chunk_documents(
            documents,
            chunk_size_tokens=self.config.collections.text.chunk_size_tokens,
            chunk_overlap_tokens=self.config.collections.text.chunk_overlap_tokens,
        )
        text_points: list[Any] = []
        visual_points: list[Any] = []
        for chunk in chunks:
            point = self._point_from_chunk(chunk)
            if chunk.modality is Modality.TEXT:
                text_points.append(point)
            else:
                visual_points.append(point)
        if text_points:
            self._client.upsert(collection_name=self.text_collection, points=text_points)
        if visual_points:
            self._client.upsert(collection_name=self.visual_collection, points=visual_points)
        return IngestResult(
            source_ids=[document.source_id for document in documents],
            text_chunks=len(text_points),
            visual_chunks=len(visual_points),
        )

    def retrieve_text(self, query: RetrievalQuery) -> RetrievalResult:
        return self._retrieve(query, self.text_collection, query.text_top_k)

    def retrieve_visual(self, query: RetrievalQuery) -> RetrievalResult:
        return self._retrieve(query, self.visual_collection, query.visual_top_k)

    def retrieve_fused(self, query: RetrievalQuery) -> RetrievalResult:
        evidence = [
            *self.retrieve_text(query).evidence,
            *self.retrieve_visual(query).evidence,
        ]
        evidence.sort(key=lambda item: item.score, reverse=True)
        fused = evidence[: self.config.retrieval.fused_top_k]

        if self._reranker and fused:
            fused = _apply_reranker(self._reranker, query.query, fused)

        return RetrievalResult(query=query, evidence=fused)

    def _ensure_collections(self) -> None:
        if self._collections_ready:
            return
        vector_params = self._models_module.VectorParams(
            size=self.embedding_model.dimension,
            distance=self._models_module.Distance.COSINE,
        )
        for collection in [self.text_collection, self.visual_collection]:
            if not self._client.collection_exists(collection):
                self._client.create_collection(
                    collection_name=collection,
                    vectors_config=vector_params,
                )
        self._collections_ready = True

    def _point_from_chunk(self, chunk: IngestChunk) -> Any:
        payload = chunk.model_dump(mode="json")
        vector = self.embedding_model.embed(self._embedding_text(chunk))
        return self._models_module.PointStruct(
            id=_stable_point_id(chunk.chunk_id),
            vector=vector,
            payload=payload,
        )

    def _retrieve(self, query: RetrievalQuery, collection: str, top_k: int) -> RetrievalResult:
        self._ensure_collections()
        vector = self.embedding_model.embed(query.query)
        search_filter = self._build_filter(query)
        points = self._client.search(
            collection_name=collection,
            query_vector=vector,
            query_filter=search_filter,
            limit=top_k,
            with_payload=True,
        )
        evidence = [_point_to_evidence(point) for point in points]
        return RetrievalResult(query=query, evidence=evidence)

    def _build_filter(self, query: RetrievalQuery) -> Any | None:
        conditions: list[Any] = []
        if query.tenant_id is not None:
            conditions.append(
                self._models_module.FieldCondition(
                    key="tenant_id",
                    match=self._models_module.MatchValue(value=query.tenant_id),
                )
            )
        for key, value in query.filters.items():
            conditions.append(
                self._models_module.FieldCondition(
                    key=f"metadata.{key}",
                    match=self._models_module.MatchValue(value=value),
                )
            )
        if not conditions:
            return None
        return self._models_module.Filter(must=conditions)

    def _embedding_text(self, chunk: IngestChunk) -> str:
        return " ".join(
            value
            for value in [chunk.content, chunk.artifact_uri, str(chunk.metadata)]
            if value is not None
        )


def _stable_point_id(value: str) -> str:
    digest = hashlib.sha256(value.encode("utf-8")).hexdigest()[:32]
    return str(UUID(digest))


def _apply_reranker(
    reranker: Reranker, query: str, evidence: list[RetrievalEvidence]
) -> list[RetrievalEvidence]:
    """Rerank evidence list using the provided reranker."""
    documents = [item.content or "" for item in evidence]
    scored = reranker.rerank(query, documents)
    return [
        RetrievalEvidence(
            source_id=evidence[item.index].source_id,
            modality=evidence[item.index].modality,
            score=item.score,
            content=evidence[item.index].content,
            artifact_uri=evidence[item.index].artifact_uri,
            metadata=evidence[item.index].metadata,
        )
        for item in scored
    ]


def _point_to_evidence(point: Any) -> RetrievalEvidence:
    payload = point.payload or {}
    metadata = payload.get("metadata") or {}
    if not isinstance(metadata, dict):
        metadata = {}
    return RetrievalEvidence(
        source_id=str(payload.get("source_id", "unknown")),
        modality=Modality(str(payload.get("modality", Modality.TEXT))),
        score=float(point.score),
        content=payload.get("content"),
        artifact_uri=payload.get("artifact_uri"),
        metadata={**metadata, "chunk_id": payload.get("chunk_id")},
    )
