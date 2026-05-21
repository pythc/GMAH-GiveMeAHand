from fastapi.testclient import TestClient

from agent_workflow.api.app import create_app


def test_api_ingests_and_retrieves_rag_documents() -> None:
    client = TestClient(create_app())

    ingest = client.post(
        "/rag/ingest",
        json={
            "documents": [
                {
                    "source_id": "api-doc-1",
                    "text": "LangGraph coordinates tool calls with Redis checkpoints.",
                    "pages": [
                        {
                            "page_number": 1,
                            "artifact_uri": "oss://bucket/api-doc-1-page-1.png",
                            "text": "visual page about LangGraph and Qdrant",
                        }
                    ],
                }
            ]
        },
    )
    assert ingest.status_code == 200
    assert ingest.json()["text_chunks"] == 1

    retrieve = client.post("/rag/retrieve/fused", json={"query": "LangGraph Qdrant Redis"})
    text = client.post("/rag/retrieve/text", json={"query": "Redis checkpoints"})
    visual = client.post("/rag/retrieve/visual", json={"query": "visual page"})

    assert retrieve.status_code == 200
    assert retrieve.json()["evidence"]
    assert text.status_code == 200
    assert visual.status_code == 200
