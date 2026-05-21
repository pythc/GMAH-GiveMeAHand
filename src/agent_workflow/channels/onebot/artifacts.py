"""Build project evaluation inputs from extracted QQ archive files."""

import re
import zipfile
from pathlib import Path
from xml.etree import ElementTree as ET

from pydantic import BaseModel, Field

from agent_workflow.channels.onebot.archive import ArchiveExtractionResult
from agent_workflow.evaluation.models import ArtifactInput, ArtifactKind, ProjectEvaluationRequest

TEXT_SUFFIXES = {".md", ".txt", ".rst"}
REPORT_SUFFIXES = {".md", ".txt", ".docx", ".pdf"}
PRESENTATION_SUFFIXES = {".ppt", ".pptx"}
VIDEO_SUFFIXES = {".mp4", ".mov", ".m4a", ".mp3", ".wav"}
CODE_SUFFIXES = {".py", ".ts", ".tsx", ".js", ".go", ".java", ".rs"}
DATA_SUFFIXES = {".csv", ".jsonl", ".parquet", ".xlsx"}
PARSEABLE_SUFFIXES = {".md", ".txt", ".rst", ".docx", ".pptx", ".pdf", ".html", ".htm"}


class ArchiveEvaluationBuildResult(BaseModel):
    request: ProjectEvaluationRequest
    artifacts: list[ArtifactInput] = Field(default_factory=list)


def build_evaluation_request_from_extraction(
    extraction: ArchiveExtractionResult,
    *,
    topic_title: str,
    topic_goal: str,
) -> ProjectEvaluationRequest:
    artifacts = _artifacts_from_files([Path(path) for path in extraction.extracted_files])
    if not artifacts:
        artifacts = [
            ArtifactInput(
                artifact_id="archive-summary",
                kind=ArtifactKind.OTHER,
                title=Path(extraction.archive_path).name,
                uri=extraction.archive_path,
                metadata={"detected_artifacts": extraction.inspection.detected_artifacts},
            )
        ]
    return ProjectEvaluationRequest(
        topic_title=topic_title,
        topic_goal=topic_goal,
        artifacts=artifacts,
    )


def _artifacts_from_files(files: list[Path]) -> list[ArtifactInput]:
    artifacts: list[ArtifactInput] = []
    code_files: list[Path] = []
    for path in files:
        suffix = path.suffix.lower()
        lower_name = path.name.lower()
        if suffix in CODE_SUFFIXES or lower_name in {
            "readme.md", "pyproject.toml", "package.json"
        }:
            code_files.append(path)
            continue
        kind = _artifact_kind(path)
        if kind is None:
            continue
        # Extract text content for all parseable formats
        text_content = _extract_file_text(path) if suffix in PARSEABLE_SUFFIXES else None
        artifacts.append(
            ArtifactInput(
                artifact_id=_artifact_id(path),
                kind=kind,
                title=path.name,
                uri=str(path),
                text=text_content,
                transcript=_read_text_preview(path) if suffix in {".srt", ".vtt"} else None,
                metadata={"suffix": suffix, "size_bytes": _safe_size(path)},
            )
        )

    if code_files:
        artifacts.append(_code_repository_artifact(code_files))
    return artifacts


def _artifact_kind(path: Path) -> ArtifactKind | None:
    suffix = path.suffix.lower()
    lower = path.as_posix().lower()
    if suffix in PRESENTATION_SUFFIXES:
        return ArtifactKind.PRESENTATION
    if suffix in VIDEO_SUFFIXES:
        return ArtifactKind.VIDEO
    if suffix in DATA_SUFFIXES:
        return ArtifactKind.DATASET
    if "log" in lower or "result" in lower:
        return ArtifactKind.EXPERIMENT_LOG
    if suffix in REPORT_SUFFIXES:
        return ArtifactKind.PAPER if "paper" in lower or "论文" in lower else ArtifactKind.REPORT
    return None


def _code_repository_artifact(files: list[Path]) -> ArtifactInput:
    names = [path.name for path in files[:50]]
    summary = "代码仓库包含文件：" + ", ".join(names)
    signals = []
    lower_names = {name.lower() for name in names}
    if "readme.md" in lower_names:
        signals.append("README")
        # Also read README content
        for path in files:
            if path.name.lower() == "readme.md":
                content = _read_text_preview(path, max_chars=30_000)
                if content:
                    summary += f"\n\nREADME 内容：\n{content}"
                break
    if "pyproject.toml" in lower_names or "package.json" in lower_names:
        signals.append("依赖配置")
    if any("test" in path.as_posix().lower() for path in files):
        signals.append("测试文件")
    if signals:
        summary += "\n识别到：" + "、".join(signals)
    return ArtifactInput(
        artifact_id="code-repository",
        kind=ArtifactKind.CODE_REPOSITORY,
        title="代码仓库",
        repository_summary=summary,
        metadata={"file_count": len(files)},
    )


def _artifact_id(path: Path) -> str:
    return path.as_posix().replace("/", "_").replace(" ", "_")[-120:]


def _extract_file_text(path: Path, max_chars: int = 50_000) -> str | None:
    """Extract text content from various file formats."""
    suffix = path.suffix.lower()
    try:
        if suffix in {".md", ".txt", ".rst", ".html", ".htm"}:
            return path.read_text(encoding="utf-8", errors="ignore")[:max_chars]
        if suffix == ".docx":
            return _extract_docx(path)[:max_chars]
        if suffix == ".pptx":
            return _extract_pptx(path)[:max_chars]
        if suffix == ".pdf":
            return _extract_pdf(path)[:max_chars]
    except Exception:  # noqa: BLE001 - best effort extraction
        return None
    return None


def _extract_docx(path: Path) -> str:
    """Extract text from .docx file."""
    with zipfile.ZipFile(path) as archive:
        xml = archive.read("word/document.xml")
    return _xml_all_text(xml)


def _extract_pptx(path: Path) -> str:
    """Extract text from .pptx file."""
    texts: list[str] = []
    with zipfile.ZipFile(path) as archive:
        slide_names = sorted(
            name for name in archive.namelist() if name.startswith("ppt/slides/slide")
        )
        for name in slide_names:
            slide_text = _xml_all_text(archive.read(name))
            if slide_text.strip():
                texts.append(f"[Slide] {slide_text.strip()}")
    return "\n\n".join(texts)


def _extract_pdf(path: Path) -> str:
    """Rough text extraction from PDF."""
    data = path.read_bytes()
    text = data.decode("latin-1", errors="ignore")
    chunks = re.findall(r"\(([^()]{0,2000})\)", text)
    if chunks:
        return "\n".join(chunks)
    return re.sub(r"[^\x20-\x7E一-鿿]+", " ", text)[:50_000]


def _xml_all_text(data: bytes) -> str:
    """Extract all text nodes from an XML document."""
    root = ET.fromstring(data)
    values = [node.text for node in root.iter() if node.text and node.text.strip()]
    return "\n".join(values)


def _read_text_preview(path: Path, max_chars: int = 20_000) -> str | None:
    try:
        return path.read_text(encoding="utf-8", errors="ignore")[:max_chars]
    except OSError:
        return None


def _safe_size(path: Path) -> int:
    try:
        return path.stat().st_size
    except OSError:
        return 0
