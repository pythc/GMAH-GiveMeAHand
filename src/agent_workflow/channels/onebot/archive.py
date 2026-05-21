"""Safe archive inspection for QQ/NapCat uploaded project bundles."""

import tarfile
import zipfile
from enum import StrEnum
from pathlib import Path, PurePosixPath

from pydantic import BaseModel, Field


class ArchiveKind(StrEnum):
    ZIP = "zip"
    TAR = "tar"
    UNSUPPORTED = "unsupported"


class ArchiveEntry(BaseModel):
    path: str
    size_bytes: int = Field(ge=0)
    is_dir: bool = False
    suspicious: bool = False
    reason: str | None = None


class ArchiveInspectionResult(BaseModel):
    path: str
    kind: ArchiveKind
    safe: bool
    total_files: int = 0
    total_size_bytes: int = 0
    entries: list[ArchiveEntry] = Field(default_factory=list)
    detected_artifacts: dict[str, int] = Field(default_factory=dict)
    errors: list[str] = Field(default_factory=list)


class ArchiveExtractionResult(BaseModel):
    archive_path: str
    destination_dir: str
    inspection: ArchiveInspectionResult
    extracted_files: list[str] = Field(default_factory=list)


class ArchiveSafetyPolicy(BaseModel):
    max_files: int = Field(default=2000, gt=0)
    max_total_size_bytes: int = Field(default=500 * 1024 * 1024, gt=0)
    max_entry_size_bytes: int = Field(default=100 * 1024 * 1024, gt=0)


class ArchiveInspector:
    """Inspect archive metadata without extracting it."""

    def __init__(self, policy: ArchiveSafetyPolicy | None = None) -> None:
        self.policy = policy or ArchiveSafetyPolicy()

    def inspect(self, path: Path) -> ArchiveInspectionResult:
        kind = _archive_kind(path)
        if kind is ArchiveKind.UNSUPPORTED:
            return ArchiveInspectionResult(
                path=str(path),
                kind=kind,
                safe=False,
                errors=["unsupported archive type"],
            )
        if not path.exists() or not path.is_file():
            return ArchiveInspectionResult(
                path=str(path),
                kind=kind,
                safe=False,
                errors=["archive file does not exist"],
            )

        try:
            entries = self._read_entries(path, kind)
        except (OSError, tarfile.TarError, zipfile.BadZipFile) as exc:
            return ArchiveInspectionResult(
                path=str(path),
                kind=kind,
                safe=False,
                errors=[str(exc)],
            )

        total_files = sum(1 for entry in entries if not entry.is_dir)
        total_size = sum(entry.size_bytes for entry in entries if not entry.is_dir)
        errors = _policy_errors(entries, self.policy, total_files, total_size)
        safe = not errors and not any(entry.suspicious for entry in entries)
        return ArchiveInspectionResult(
            path=str(path),
            kind=kind,
            safe=safe,
            total_files=total_files,
            total_size_bytes=total_size,
            entries=entries[: self.policy.max_files],
            detected_artifacts=_detect_artifacts(entries),
            errors=errors,
        )

    def extract_safe(self, path: Path, destination_dir: Path) -> ArchiveExtractionResult:
        inspection = self.inspect(path)
        destination = destination_dir.resolve()
        destination.mkdir(parents=True, exist_ok=True)
        extracted: list[str] = []
        if not inspection.safe:
            return ArchiveExtractionResult(
                archive_path=str(path),
                destination_dir=str(destination),
                inspection=inspection,
                extracted_files=[],
            )

        if inspection.kind is ArchiveKind.ZIP:
            with zipfile.ZipFile(path) as archive:
                for info in archive.infolist():
                    if info.is_dir():
                        continue
                    target = _safe_target(destination, info.filename)
                    target.parent.mkdir(parents=True, exist_ok=True)
                    with archive.open(info) as source, target.open("wb") as output:
                        output.write(source.read())
                    extracted.append(str(target))
        elif inspection.kind is ArchiveKind.TAR:
            with tarfile.open(path) as archive:
                for member in archive.getmembers():
                    if member.isdir():
                        continue
                    target = _safe_target(destination, member.name)
                    target.parent.mkdir(parents=True, exist_ok=True)
                    tar_source = archive.extractfile(member)
                    if tar_source is not None:
                        target.write_bytes(tar_source.read())
                        extracted.append(str(target))

        return ArchiveExtractionResult(
            archive_path=str(path),
            destination_dir=str(destination),
            inspection=inspection,
            extracted_files=extracted,
        )

    def _read_entries(self, path: Path, kind: ArchiveKind) -> list[ArchiveEntry]:
        if kind is ArchiveKind.ZIP:
            with zipfile.ZipFile(path) as archive:
                return [_zip_entry(info) for info in archive.infolist()]
        with tarfile.open(path) as archive:
            return [_tar_entry(info) for info in archive.getmembers()]


def _safe_target(root: Path, member_path: str) -> Path:
    reason = _suspicious_reason(member_path)
    if reason is not None:
        raise ValueError(reason)
    target = (root / member_path).resolve()
    if not target.is_relative_to(root):
        raise ValueError("archive entry escapes destination")
    return target


def _archive_kind(path: Path) -> ArchiveKind:
    suffixes = [suffix.lower() for suffix in path.suffixes]
    if suffixes and suffixes[-1] == ".zip":
        return ArchiveKind.ZIP
    if suffixes[-2:] == [".tar", ".gz"] or (suffixes and suffixes[-1] in {".tar", ".tgz"}):
        return ArchiveKind.TAR
    return ArchiveKind.UNSUPPORTED


def _zip_entry(info: zipfile.ZipInfo) -> ArchiveEntry:
    reason = _suspicious_reason(info.filename)
    return ArchiveEntry(
        path=info.filename,
        size_bytes=max(0, info.file_size),
        is_dir=info.is_dir(),
        suspicious=reason is not None,
        reason=reason,
    )


def _tar_entry(info: tarfile.TarInfo) -> ArchiveEntry:
    reason = _suspicious_reason(info.name)
    if info.issym() or info.islnk():
        reason = reason or "archive entry is a link"
    return ArchiveEntry(
        path=info.name,
        size_bytes=max(0, info.size),
        is_dir=info.isdir(),
        suspicious=reason is not None,
        reason=reason,
    )


def _suspicious_reason(path: str) -> str | None:
    normalized = PurePosixPath(path.replace("\\", "/"))
    if normalized.is_absolute():
        return "absolute path is not allowed"
    if ".." in normalized.parts:
        return "path traversal is not allowed"
    if not path or path.startswith("~"):
        return "suspicious path"
    return None


def _policy_errors(
    entries: list[ArchiveEntry],
    policy: ArchiveSafetyPolicy,
    total_files: int,
    total_size: int,
) -> list[str]:
    errors: list[str] = []
    if total_files > policy.max_files:
        errors.append(f"too many files: {total_files} > {policy.max_files}")
    if total_size > policy.max_total_size_bytes:
        errors.append(f"archive too large: {total_size} > {policy.max_total_size_bytes}")
    large_entries = [
        entry.path for entry in entries if entry.size_bytes > policy.max_entry_size_bytes
    ]
    if large_entries:
        errors.append(f"entries too large: {', '.join(large_entries[:5])}")
    return errors


def _detect_artifacts(entries: list[ArchiveEntry]) -> dict[str, int]:
    counters = {
        "reports": 0,
        "papers": 0,
        "presentations": 0,
        "videos": 0,
        "code_files": 0,
        "datasets": 0,
        "experiment_logs": 0,
    }
    for entry in entries:
        if entry.is_dir:
            continue
        path = entry.path.lower()
        suffix = Path(path).suffix
        if suffix in {".md", ".docx", ".pdf"}:
            if "paper" in path or "论文" in path:
                counters["papers"] += 1
            else:
                counters["reports"] += 1
        if suffix in {".ppt", ".pptx"}:
            counters["presentations"] += 1
        if suffix in {".mp4", ".mov", ".m4a", ".mp3", ".wav"}:
            counters["videos"] += 1
        if suffix in {".py", ".ts", ".tsx", ".js", ".go", ".java", ".rs"}:
            counters["code_files"] += 1
        if suffix in {".csv", ".jsonl", ".parquet", ".xlsx"}:
            counters["datasets"] += 1
        if "log" in path or "result" in path:
            counters["experiment_logs"] += 1
    return counters
