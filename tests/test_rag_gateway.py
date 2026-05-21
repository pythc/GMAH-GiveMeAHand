from agent_workflow.rag.local_gateway import InMemoryRagGateway
from agent_workflow.rag.models import IngestDocument, IngestPage, Modality, RetrievalQuery


def test_in_memory_rag_ingests_text_and_visual_pages() -> None:
    gateway = InMemoryRagGateway()
    result = gateway.ingest_documents(
        [
            IngestDocument(
                source_id="doc-1",
                text="Qdrant supports hybrid retrieval for agent memory and RAG.",
                pages=[
                    IngestPage(
                        page_number=1,
                        artifact_uri="oss://bucket/doc-1-page-1.png",
                        text="architecture diagram with Qdrant and Redis",
                    )
                ],
            )
        ]
    )

    assert result.text_chunks == 1
    assert result.visual_chunks == 1

    text = gateway.retrieve_text(RetrievalQuery(query="hybrid retrieval Qdrant"))
    visual = gateway.retrieve_visual(RetrievalQuery(query="architecture diagram Redis"))
    fused = gateway.retrieve_fused(RetrievalQuery(query="Qdrant Redis architecture"))

    assert text.evidence[0].source_id == "doc-1"
    assert visual.evidence[0].modality is Modality.PAGE
    assert len(fused.evidence) == 2
