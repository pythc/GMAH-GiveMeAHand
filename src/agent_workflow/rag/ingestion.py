"""Text and page chunking for multimodal RAG ingestion."""

from agent_workflow.rag.models import IngestChunk, IngestDocument, Modality


def chunk_documents(
    documents: list[IngestDocument],
    *,
    chunk_size_tokens: int,
    chunk_overlap_tokens: int,
) -> list[IngestChunk]:
    """Split documents into text chunks and page/image chunks."""

    chunks: list[IngestChunk] = []
    for document in documents:
        if document.text:
            chunks.extend(
                _chunk_text_document(
                    document,
                    chunk_size_tokens=chunk_size_tokens,
                    chunk_overlap_tokens=chunk_overlap_tokens,
                )
            )
        for page in document.pages:
            chunks.append(
                IngestChunk(
                    chunk_id=f"{document.source_id}:page:{page.page_number}",
                    source_id=document.source_id,
                    modality=Modality.PAGE,
                    content=page.text,
                    artifact_uri=page.artifact_uri,
                    tenant_id=document.tenant_id,
                    metadata={
                        **document.metadata,
                        **page.metadata,
                        "page_number": page.page_number,
                    },
                )
            )
    return chunks


def _chunk_text_document(
    document: IngestDocument,
    *,
    chunk_size_tokens: int,
    chunk_overlap_tokens: int,
) -> list[IngestChunk]:
    text = document.text or ""
    tokens = text.split()
    if not tokens:
        return []

    step = max(1, chunk_size_tokens - chunk_overlap_tokens)
    chunks: list[IngestChunk] = []
    chunk_index = 0
    for start in range(0, len(tokens), step):
        end = min(start + chunk_size_tokens, len(tokens))
        chunk_text = " ".join(tokens[start:end])
        chunks.append(
            IngestChunk(
                chunk_id=f"{document.source_id}:text:{chunk_index}",
                source_id=document.source_id,
                modality=Modality.TEXT,
                content=chunk_text,
                tenant_id=document.tenant_id,
                metadata={**document.metadata, "chunk_index": chunk_index},
            )
        )
        chunk_index += 1
        if end == len(tokens):
            break
    return chunks
