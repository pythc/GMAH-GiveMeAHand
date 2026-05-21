"""RAG ingestion and retrieval HTTP routes."""

import base64
import re
import zipfile
from pathlib import Path
from typing import Annotated
from xml.etree import ElementTree as ET

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from agent_workflow.api.dependencies import get_rag_gateway
from agent_workflow.rag.gateway import RagGateway
from agent_workflow.rag.models import IngestDocument, IngestResult, RetrievalQuery, RetrievalResult

router = APIRouter(prefix="/rag", tags=["rag"])
RagDep = Annotated[RagGateway, Depends(get_rag_gateway)]
_UPLOAD_DIR = Path("data/rag-uploads")


class IngestDocumentsRequest(BaseModel):
    documents: list[IngestDocument] = Field(default_factory=list)


class UploadRagDocumentRequest(BaseModel):
    filename: str
    content_base64: str
    source_id: str | None = None
    tenant_id: str | None = None
    description: str | None = None


@router.post("/ingest")
def ingest_documents(request: IngestDocumentsRequest, rag_gateway: RagDep) -> IngestResult:
    return rag_gateway.ingest_documents(request.documents)


@router.post("/upload")
def upload_document(request: UploadRagDocumentRequest, rag_gateway: RagDep) -> IngestResult:
    data = base64.b64decode(request.content_base64)
    safe_name = Path(request.filename).name or "uploaded-document"
    _UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    path = _UPLOAD_DIR / safe_name
    path.write_bytes(data)
    text = _extract_upload_text(safe_name, data)
    document = IngestDocument(
        source_id=request.source_id or safe_name,
        tenant_id=request.tenant_id,
        text=text,
        metadata={
            "filename": safe_name,
            "path": str(path),
            "description": request.description,
            "source": "ui-upload",
        },
    )
    return rag_gateway.ingest_documents([document])


@router.post("/retrieve/text")
def retrieve_text(query: RetrievalQuery, rag_gateway: RagDep) -> RetrievalResult:
    return rag_gateway.retrieve_text(query)


@router.post("/retrieve/visual")
def retrieve_visual(query: RetrievalQuery, rag_gateway: RagDep) -> RetrievalResult:
    return rag_gateway.retrieve_visual(query)


@router.post("/retrieve/fused")
def retrieve_fused(query: RetrievalQuery, rag_gateway: RagDep) -> RetrievalResult:
    return rag_gateway.retrieve_fused(query)


def _extract_upload_text(filename: str, data: bytes) -> str:
    suffix = Path(filename).suffix.lower()
    if suffix in {".txt", ".md", ".rst", ".html", ".htm", ".csv", ".json", ".yaml", ".yml"}:
        return data.decode("utf-8", errors="ignore")[:300_000]
    if suffix == ".docx":
        return _extract_docx_text(data)[:300_000]
    if suffix == ".pptx":
        return _extract_pptx_text(data)[:300_000]
    if suffix == ".pdf":
        return _rough_pdf_text(data)[:300_000]
    return data.decode("utf-8", errors="ignore")[:300_000] or f"已上传参考资料：{filename}"


def _extract_docx_text(data: bytes) -> str:
    with zipfile.ZipFile(_BytesReader(data)) as archive:
        xml = archive.read("word/document.xml")
    return _xml_text(xml)


def _extract_pptx_text(data: bytes) -> str:
    texts: list[str] = []
    with zipfile.ZipFile(_BytesReader(data)) as archive:
        names = sorted(name for name in archive.namelist() if name.startswith("ppt/slides/slide"))
        for name in names:
            texts.append(_xml_text(archive.read(name)))
    return "\n\n".join(texts)


def _rough_pdf_text(data: bytes) -> str:
    text = data.decode("latin-1", errors="ignore")
    chunks = re.findall(r"\(([^()] {0,2000})\)", text)
    if chunks:
        return "\n".join(chunks)
    return re.sub(r"[^\x20-\x7E\u4e00-\u9fff]+", " ", text)[:50_000]


def _xml_text(data: bytes) -> str:
    root = ET.fromstring(data)
    values = [node.text for node in root.iter() if node.text]
    return "\n".join(values)


class _BytesReader:
    def __init__(self, data: bytes) -> None:
        self._data = data
        self._pos = 0

    def read(self, size: int = -1) -> bytes:
        if size < 0:
            size = len(self._data) - self._pos
        chunk = self._data[self._pos : self._pos + size]
        self._pos += len(chunk)
        return chunk

    def seek(self, offset: int, whence: int = 0) -> int:
        if whence == 0:
            self._pos = offset
        elif whence == 1:
            self._pos += offset
        elif whence == 2:
            self._pos = len(self._data) + offset
        return self._pos

    def tell(self) -> int:
        return self._pos
