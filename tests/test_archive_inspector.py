import tarfile
import zipfile
from pathlib import Path

from agent_workflow.channels.onebot.archive import (
    ArchiveInspector,
    ArchiveKind,
    ArchiveSafetyPolicy,
)


def test_archive_inspector_detects_zip_artifacts(tmp_path: Path) -> None:
    archive_path = tmp_path / "project.zip"
    with zipfile.ZipFile(archive_path, "w") as archive:
        archive.writestr("README.md", "readme")
        archive.writestr("paper.pdf", "pdf")
        archive.writestr("slides.pptx", "ppt")
        archive.writestr("src/main.py", "print('ok')")
        archive.writestr("data/result.csv", "a,b")

    result = ArchiveInspector().inspect(archive_path)

    assert result.kind is ArchiveKind.ZIP
    assert result.safe is True
    assert result.detected_artifacts["papers"] == 1
    assert result.detected_artifacts["presentations"] == 1
    assert result.detected_artifacts["code_files"] == 1
    assert result.detected_artifacts["datasets"] == 1


def test_archive_inspector_flags_zip_slip_and_limits(tmp_path: Path) -> None:
    archive_path = tmp_path / "bad.zip"
    with zipfile.ZipFile(archive_path, "w") as archive:
        archive.writestr("../evil.py", "bad")
        archive.writestr("huge.bin", "x" * 20)

    result = ArchiveInspector(
        ArchiveSafetyPolicy(max_files=10, max_total_size_bytes=10, max_entry_size_bytes=10)
    ).inspect(archive_path)

    assert result.safe is False
    assert result.entries[0].suspicious is True
    assert result.errors


def test_archive_inspector_supports_tar_and_unsupported(tmp_path: Path) -> None:
    source = tmp_path / "report.md"
    source.write_text("report", encoding="utf-8")
    tar_path = tmp_path / "bundle.tar.gz"
    with tarfile.open(tar_path, "w:gz") as archive:
        archive.add(source, arcname="report.md")

    tar_result = ArchiveInspector().inspect(tar_path)
    unsupported = ArchiveInspector().inspect(tmp_path / "bundle.rar")

    assert tar_result.kind is ArchiveKind.TAR
    assert tar_result.safe is True
    assert unsupported.kind is ArchiveKind.UNSUPPORTED
    assert unsupported.safe is False
