"""In-memory multimodal RAG gateway for local development and tests."""

from __future__ import annotations

from dataclasses import dataclass

from agent_workflow.rag.config import RagConfig
from agent_workflow.rag.embeddings import (
    EmbeddingModel,
    HashEmbeddingModel,
    Reranker,
    cosine_similarity,
)
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


@dataclass(frozen=True)
class _IndexedChunk:
    chunk: IngestChunk
    vector: list[float]


class InMemoryRagGateway:
    """Process-local text + visual retrieval gateway."""

    def __init__(
        self,
        config: RagConfig | None = None,
        embedding_model: EmbeddingModel | None = None,
        reranker: Reranker | None = None,
    ) -> None:
        self.config = config or RagConfig()
        self.embedding_model = embedding_model or HashEmbeddingModel()
        self._reranker = reranker
        self._text_chunks: list[_IndexedChunk] = []
        self._visual_chunks: list[_IndexedChunk] = []

    def ingest_documents(self, documents: list[IngestDocument]) -> IngestResult:
        chunks = chunk_documents(
            documents,
            chunk_size_tokens=self.config.collections.text.chunk_size_tokens,
            chunk_overlap_tokens=self.config.collections.text.chunk_overlap_tokens,
        )
        text_count = 0
        visual_count = 0
        for chunk in chunks:
            vector = self.embedding_model.embed(self._embedding_text(chunk))
            indexed = _IndexedChunk(chunk=chunk, vector=vector)
            if chunk.modality is Modality.TEXT:
                self._text_chunks.append(indexed)
                text_count += 1
            else:
                self._visual_chunks.append(indexed)
                visual_count += 1
        return IngestResult(
            source_ids=[document.source_id for document in documents],
            text_chunks=text_count,
            visual_chunks=visual_count,
        )

    def retrieve_text(self, query: RetrievalQuery) -> RetrievalResult:
        return self._retrieve(query, self._text_chunks, query.text_top_k)

    def retrieve_visual(self, query: RetrievalQuery) -> RetrievalResult:
        return self._retrieve(query, self._visual_chunks, query.visual_top_k)

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

    def _retrieve(
        self,
        query: RetrievalQuery,
        chunks: list[_IndexedChunk],
        top_k: int,
    ) -> RetrievalResult:
        query_vector = self.embedding_model.embed(query.query)
        scored: list[RetrievalEvidence] = []
        for indexed in chunks:
            chunk = indexed.chunk
            if query.tenant_id is not None and chunk.tenant_id != query.tenant_id:
                continue
            if not _metadata_matches(chunk.metadata, query.filters):
                continue
            score = cosine_similarity(query_vector, indexed.vector)
            scored.append(_to_evidence(chunk, score))
        scored.sort(key=lambda item: item.score, reverse=True)
        return RetrievalResult(query=query, evidence=scored[:top_k])

    def _embedding_text(self, chunk: IngestChunk) -> str:
        return " ".join(
            value
            for value in [chunk.content, chunk.artifact_uri, str(chunk.metadata)]
            if value is not None
        )


def _metadata_matches(metadata: dict[str, object], filters: dict[str, object]) -> bool:
    return all(metadata.get(key) == value for key, value in filters.items())


def _to_evidence(chunk: IngestChunk, score: float) -> RetrievalEvidence:
    return RetrievalEvidence(
        source_id=chunk.source_id,
        modality=chunk.modality,
        score=score,
        content=chunk.content,
        artifact_uri=chunk.artifact_uri,
        metadata={**chunk.metadata, "chunk_id": chunk.chunk_id},
    )


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
