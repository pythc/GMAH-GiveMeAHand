import math

from agent_workflow.rag.embeddings import HashEmbeddingModel, cosine_similarity, normalize
from agent_workflow.rag.ingestion import chunk_documents
from agent_workflow.rag.local_gateway import InMemoryRagGateway
from agent_workflow.rag.models import IngestDocument, IngestPage, RetrievalQuery


def test_hash_embedding_is_deterministic_and_normalized() -> None:
    model = HashEmbeddingModel(dimension=16)
    first = model.embed("alpha beta")
    second = model.embed("alpha beta")

    assert first == second
    assert len(first) == 16
    assert math.isclose(sum(value * value for value in first), 1.0)
    assert normalize([0.0, 0.0]) == [0.0, 0.0]
    assert cosine_similarity(first, first) > 0.99


def test_chunk_documents_handles_overlap_pages_and_empty_text() -> None:
    chunks = chunk_documents(
        [
            IngestDocument(
                source_id="doc-1",
                text="one two three four five",
                tenant_id="tenant-1",
                pages=[IngestPage(page_number=1, artifact_uri="oss://page.png", text="diagram")],
                metadata={"course": "ml"},
            ),
            IngestDocument(source_id="empty", text="   "),
        ],
        chunk_size_tokens=3,
        chunk_overlap_tokens=1,
    )

    assert [chunk.chunk_id for chunk in chunks] == [
        "doc-1:text:0",
        "doc-1:text:1",
        "doc-1:page:1",
    ]
    assert chunks[0].content == "one two three"
    assert chunks[1].content == "three four five"
    assert chunks[2].metadata["page_number"] == 1


def test_in_memory_rag_filters_by_tenant_and_metadata() -> None:
    gateway = InMemoryRagGateway()
    gateway.ingest_documents(
        [
            IngestDocument(
                source_id="doc-1",
                text="redis checkpoint state",
                tenant_id="tenant-a",
                metadata={"course": "ml"},
            ),
            IngestDocument(
                source_id="doc-2",
                text="redis unrelated state",
                tenant_id="tenant-b",
                metadata={"course": "math"},
            ),
        ]
    )

    result = gateway.retrieve_text(
        RetrievalQuery(query="redis state", tenant_id="tenant-a", filters={"course": "ml"})
    )

    assert len(result.evidence) == 1
    assert result.evidence[0].source_id == "doc-1"
