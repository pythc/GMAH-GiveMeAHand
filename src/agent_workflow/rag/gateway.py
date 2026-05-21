"""RAG gateway protocol."""

from typing import Protocol

from agent_workflow.rag.models import IngestDocument, IngestResult, RetrievalQuery, RetrievalResult


class RagGateway(Protocol):
    def ingest_documents(self, documents: list[IngestDocument]) -> IngestResult:
        """Ingest text chunks and page/image evidence into retrieval indexes."""

    def retrieve_text(self, query: RetrievalQuery) -> RetrievalResult:
        """Retrieve text chunks from the text index."""

    def retrieve_visual(self, query: RetrievalQuery) -> RetrievalResult:
        """Retrieve page/image evidence from the visual index."""

    def retrieve_fused(self, query: RetrievalQuery) -> RetrievalResult:
        """Retrieve, fuse, rerank, and return evidence for context building."""
