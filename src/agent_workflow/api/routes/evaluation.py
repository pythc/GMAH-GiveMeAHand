"""Research project evaluation routes — review, history, tool logs, references."""

import json
import uuid
from pathlib import Path
from typing import Annotated, Any

from fastapi import APIRouter, Depends, File, Form, Request, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from agent_workflow.api.dependencies import get_rag_gateway
from agent_workflow.channels.onebot.archive import ArchiveInspector
from agent_workflow.channels.onebot.artifacts import build_evaluation_request_from_extraction
from agent_workflow.evaluation.history import ReviewHistoryRecord, ReviewHistoryStore
from agent_workflow.evaluation.models import (
    EvaluationRubric,
    ProjectEvaluationRequest,
    ProjectEvaluationResult,
)
from agent_workflow.evaluation.repository_agent import AgenticRepositoryReviewer
from agent_workflow.evaluation.service import ProjectEvaluationService
from agent_workflow.evaluation.tool_log import ToolLogEntry, get_tool_log_store
from agent_workflow.llm.openai_compatible import OpenAICompatibleChatClient
from agent_workflow.rag.gateway import RagGateway
from agent_workflow.rag.models import IngestDocument, RetrievalQuery

router = APIRouter(prefix="/evaluation", tags=["evaluation"])
RagDep = Annotated[RagGateway, Depends(get_rag_gateway)]

_service = ProjectEvaluationService()
_history_store = ReviewHistoryStore()
_reviewer = AgenticRepositoryReviewer(history_store=_history_store)
_inspector = ArchiveInspector()
_REFERENCE_DIR = Path("data/rag-references")
_REFERENCE_INDEX = _REFERENCE_DIR / "_index.json"
_EXTRACT_DIR = Path("data/evaluation-extracted")

DEFAULT_AGENT_SYSTEM_PROMPT = (
    "你是课题产物评价智能体。\n\n"
    "你的目标：通过只读工具自主分析代码仓库/压缩包/报告等课题产物，"
    "并给出可信、可解释、可落地的评价。\n\n"
    "可用工具：clone_repository、list_files、read_file、inspect_archive、"
    "retrieve_rag、get_review_history、update_review_history、"
    "send_progress、final_answer。\n\n"
    "行为要求：\n"
    "1. 必须基于真实工具结果评价，不要编造未读取的内容。\n"
    "2. 逐步查看目录、说明文档、依赖配置、核心代码、测试和 CI 配置。\n"
    "3. get_review_history 和 update_review_history 必须在 final_answer 前调用。\n"
    "4. 如果和上次评价相比没有明显优化，update_review_history 时 improved=false。\n"
    "5. 最终评价包含完成度、关键证据、主要不足、代码/工程质量、可复现性和建议。\n"
    "6. 使用简体中文。\n"
)


# ─── Models ───────────────────────────────────────────────────────────────────


class ReviewRequest(BaseModel):
    source_url: str | None = None
    archive_path: str | None = None
    topic_title: str = Field(min_length=1)
    topic_goal: str = Field(min_length=1)


class ReviewResponse(BaseModel):
    session_id: str
    evaluation: ProjectEvaluationResult | None = None
    llm_review: str | None = None
    history_record: ReviewHistoryRecord | None = None
    history_comparison: str | None = None


class ReferenceDocument(BaseModel):
    ref_id: str
    filename: str
    description: str
    path: str
    text_chunks: int
    uploaded_at: str


class ReferenceListResponse(BaseModel):
    references: list[ReferenceDocument]


# ─── Existing Endpoints ───────────────────────────────────────────────────────


@router.get("/rubric/default")
def get_default_rubric() -> EvaluationRubric:
    return _service.default_rubric()


@router.post("/analyze")
def analyze_project(request: ProjectEvaluationRequest) -> ProjectEvaluationResult:
    return _service.evaluate(request)


# ─── Review Endpoint ──────────────────────────────────────────────────────────


@router.post("/review")
def review_project(request_body: ReviewRequest, http_request: Request) -> ReviewResponse:
    """Trigger a full AI-driven evaluation of a repository or archive."""
    session_id = f"eval-{uuid.uuid4().hex[:12]}"
    tool_log_store = get_tool_log_store()

    chat_client = getattr(http_request.app.state, "chat_client", None)
    if not isinstance(chat_client, OpenAICompatibleChatClient):
        chat_client = None
    rag_gateway = getattr(http_request.app.state, "rag_gateway", None)
    if not hasattr(rag_gateway, "retrieve_fused"):
        rag_gateway = None

    def tool_log_callback(
        tool: str, arguments: dict[str, Any], result: dict[str, Any]
    ) -> None:
        tool_log_store.log(
            session_id=session_id, tool=tool, arguments=arguments, result=result
        )

    def rag_callback(query: str) -> list[dict[str, Any]]:
        if rag_gateway is None:
            return []
        result = rag_gateway.retrieve_fused(
            RetrievalQuery(query=query, text_top_k=8, visual_top_k=4)
        )
        return [item.model_dump() for item in result.evidence[:8]]

    # Route: GitHub URL
    if request_body.source_url:
        review = _reviewer.review_url(
            request_body.source_url,
            topic_title=request_body.topic_title,
            topic_goal=request_body.topic_goal,
            chat_client=chat_client,
            agent_system_prompt=DEFAULT_AGENT_SYSTEM_PROMPT,
            tool_log_callback=tool_log_callback,
            rag_callback=rag_callback,
        )
        eval_request = ProjectEvaluationRequest(
            topic_title=request_body.topic_title,
            topic_goal=request_body.topic_goal,
            artifacts=[review.to_artifact()],
        )
        evaluation = _service.evaluate(eval_request)
        history_record = _history_store.get(review.source_url)
        comparison = _build_comparison(history_record)
        return ReviewResponse(
            session_id=session_id,
            evaluation=evaluation,
            llm_review=review.final_review,
            history_record=history_record,
            history_comparison=comparison,
        )

    # Route: Archive path
    if request_body.archive_path:
        path = Path(request_body.archive_path)
        _EXTRACT_DIR.mkdir(parents=True, exist_ok=True)
        extraction = _inspector.extract_safe(path, _EXTRACT_DIR)
        tool_log_callback(
            "extract_archive",
            {"path": str(path)},
            {"ok": extraction.inspection.safe, "files": len(extraction.extracted_files)},
        )
        if not extraction.inspection.safe:
            return ReviewResponse(session_id=session_id, history_comparison="压缩包安全检查未通过")
        eval_request = build_evaluation_request_from_extraction(
            extraction,
            topic_title=request_body.topic_title,
            topic_goal=request_body.topic_goal,
        )
        evaluation = _service.evaluate(eval_request)
        return ReviewResponse(
            session_id=session_id,
            evaluation=evaluation,
            history_comparison="压缩包评测完成",
        )

    raise ValueError("必须提供 source_url 或 archive_path")


# ─── History Endpoints ────────────────────────────────────────────────────────


@router.get("/history")
def list_history() -> list[ReviewHistoryRecord]:
    """Return all review history records from the Excel store."""
    rows = _history_store._read_rows()
    records: list[ReviewHistoryRecord] = []
    for row in rows[1:]:
        if row and row[0]:
            from agent_workflow.evaluation.history import _row_to_record

            records.append(_row_to_record(row))
    return records


@router.get("/history/download")
def download_history_excel() -> FileResponse:
    """Download the review history Excel file."""
    if not _history_store.path.exists():
        # Create empty file if not exists
        _history_store._write_rows([["仓库链接", "课题名称", "上次评分", "上次评价",
                                     "更新时间", "工具调用摘要", "评价次数"]])
    return FileResponse(
        path=str(_history_store.path),
        filename="repository_reviews.xlsx",
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )


@router.delete("/history/{encoded_url:path}")
def delete_history_record(encoded_url: str) -> dict[str, str]:
    """Delete a history record by URL."""
    rows = _history_store._read_rows()
    new_rows = [rows[0]] + [row for row in rows[1:] if not row or row[0] != encoded_url]
    if len(new_rows) == len(rows):
        return {"status": "not_found"}
    _history_store._write_rows(new_rows)
    return {"status": "deleted"}


# ─── Tool Logs Endpoints ──────────────────────────────────────────────────────


@router.get("/tool-logs")
def list_tool_logs(
    limit: int = 200,
    session_id: str | None = None,
    kind: str | None = None,
) -> list[ToolLogEntry]:
    """Return recent activity logs (tool calls, model requests/responses, etc)."""
    from agent_workflow.evaluation.tool_log import LogKind

    log_kind = LogKind(kind) if kind else None
    return get_tool_log_store().list(limit=limit, session_id=session_id, kind=log_kind)


# ─── References Endpoints ─────────────────────────────────────────────────────


@router.post("/references/upload")
async def upload_reference(
    rag_gateway: RagDep,
    file: UploadFile = File(...),
    description: str = Form(default=""),
) -> ReferenceDocument:
    """Upload a reference document for RAG retrieval."""
    _REFERENCE_DIR.mkdir(parents=True, exist_ok=True)
    data = await file.read()
    filename = file.filename or "unnamed"
    safe_name = Path(filename).name
    ref_id = f"ref-{uuid.uuid4().hex[:8]}"
    file_path = _REFERENCE_DIR / f"{ref_id}_{safe_name}"
    file_path.write_bytes(data)

    # Extract text
    text = _extract_reference_text(safe_name, data)
    # Ingest into RAG
    document = IngestDocument(
        source_id=ref_id,
        text=text,
        metadata={
            "source": "reference",
            "filename": safe_name,
            "description": description,
            "ref_id": ref_id,
        },
    )
    result = rag_gateway.ingest_documents([document])

    # Save to index
    from datetime import UTC, datetime

    ref_doc = ReferenceDocument(
        ref_id=ref_id,
        filename=safe_name,
        description=description,
        path=str(file_path),
        text_chunks=result.text_chunks + result.visual_chunks,
        uploaded_at=datetime.now(UTC).isoformat(timespec="seconds"),
    )
    _save_reference_index(ref_doc)
    return ref_doc


@router.get("/references")
def list_references() -> ReferenceListResponse:
    """List all uploaded reference documents."""
    return ReferenceListResponse(references=_load_reference_index())


@router.delete("/references/{ref_id}")
def delete_reference(ref_id: str) -> dict[str, str]:
    """Delete a reference document."""
    refs = _load_reference_index()
    remaining = [r for r in refs if r.ref_id != ref_id]
    if len(remaining) == len(refs):
        return {"status": "not_found"}
    # Delete file
    for r in refs:
        if r.ref_id == ref_id:
            try:
                Path(r.path).unlink(missing_ok=True)
            except OSError:
                pass
    _write_reference_index(remaining)
    return {"status": "deleted"}


# ─── Helpers ──────────────────────────────────────────────────────────────────


def _build_comparison(record: ReviewHistoryRecord | None) -> str:
    if record is None:
        return "首次评测"
    score_text = f"上次评分 {record.score}" if record.score is not None else "上次无评分"
    return f"第 {record.review_count} 次评测；{score_text}；更新时间 {record.updated_at}"


def _extract_reference_text(filename: str, data: bytes) -> str:
    """Extract text from uploaded reference file. Supports many formats."""
    import re
    import zipfile
    from xml.etree import ElementTree as ET

    suffix = Path(filename).suffix.lower()
    # Plain text formats
    if suffix in {".txt", ".md", ".rst", ".html", ".htm", ".csv", ".json", ".yaml", ".yml"}:
        return data.decode("utf-8", errors="ignore")[:300_000]
    # DOCX
    if suffix == ".docx":
        try:
            from io import BytesIO

            with zipfile.ZipFile(BytesIO(data)) as archive:
                xml = archive.read("word/document.xml")
            return _xml_all_text(xml)[:300_000]
        except Exception:
            return f"已上传参考资料：{filename}"
    # PPTX
    if suffix == ".pptx":
        try:
            from io import BytesIO

            texts: list[str] = []
            with zipfile.ZipFile(BytesIO(data)) as archive:
                names = sorted(
                    n for n in archive.namelist() if n.startswith("ppt/slides/slide")
                )
                for name in names:
                    texts.append(_xml_all_text(archive.read(name)))
            return "\n\n".join(texts)[:300_000]
        except Exception:
            return f"已上传参考资料：{filename}"
    # XLSX
    if suffix == ".xlsx":
        try:
            from io import BytesIO

            with zipfile.ZipFile(BytesIO(data)) as archive:
                xml = archive.read("xl/worksheets/sheet1.xml")
            return _xml_all_text(xml)[:300_000]
        except Exception:
            return f"已上传参考资料：{filename}"
    # PDF (rough)
    if suffix == ".pdf":
        text = data.decode("latin-1", errors="ignore")
        chunks = re.findall(r"\(([^()]{0,2000})\)", text)
        if chunks:
            return "\n".join(chunks)[:300_000]
        return re.sub(r"[^\x20-\x7E一-鿿]+", " ", text)[:50_000]
    # Images — store as description only
    if suffix in {".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp", ".svg"}:
        return f"图片参考资料：{filename}"
    # Fallback
    return data.decode("utf-8", errors="ignore")[:300_000] or f"已上传参考资料：{filename}"


def _xml_all_text(data: bytes) -> str:
    from xml.etree import ElementTree as ET

    root = ET.fromstring(data)
    values = [node.text for node in root.iter() if node.text]
    return "\n".join(values)


def _load_reference_index() -> list[ReferenceDocument]:
    if not _REFERENCE_INDEX.exists():
        return []
    try:
        items = json.loads(_REFERENCE_INDEX.read_text(encoding="utf-8"))
        return [ReferenceDocument.model_validate(item) for item in items]
    except Exception:
        return []


def _save_reference_index(doc: ReferenceDocument) -> None:
    refs = _load_reference_index()
    refs.append(doc)
    _write_reference_index(refs)


def _write_reference_index(refs: list[ReferenceDocument]) -> None:
    _REFERENCE_DIR.mkdir(parents=True, exist_ok=True)
    _REFERENCE_INDEX.write_text(
        json.dumps([r.model_dump() for r in refs], ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
