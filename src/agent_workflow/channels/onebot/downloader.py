"""Download or copy OneBot/NapCat file attachments into a local workspace."""

import shutil
from pathlib import Path
from urllib.parse import urlparse

import httpx
from pydantic import BaseModel, Field

from agent_workflow.channels.events import Attachment


class DownloadedFile(BaseModel):
    source_uri: str
    path: str
    name: str
    size_bytes: int = Field(ge=0)


class FileDownloadError(RuntimeError):
    """Raised when an attachment cannot be downloaded safely."""


class OneBotFileDownloader:
    """Download HTTP/file/local attachments with size and path safeguards."""

    def __init__(
        self,
        root_dir: Path,
        *,
        max_bytes: int = 2 * 1024 * 1024 * 1024,
        client: httpx.Client | None = None,
    ) -> None:
        self.root_dir = root_dir.resolve()
        self.max_bytes = max_bytes
        self._client = client or httpx.Client(follow_redirects=True, timeout=60)
        self.root_dir.mkdir(parents=True, exist_ok=True)

    def download_attachment(self, attachment: Attachment) -> DownloadedFile:
        name = _safe_filename(attachment.name or Path(urlparse(attachment.uri).path).name or "file")
        destination = (self.root_dir / name).resolve()
        if not destination.is_relative_to(self.root_dir):
            raise FileDownloadError("download destination escapes workspace")

        parsed = urlparse(attachment.uri)
        if parsed.scheme in {"http", "https"}:
            size = self._download_http(attachment.uri, destination)
        elif parsed.scheme == "file":
            size = self._copy_local(Path(parsed.path), destination)
        else:
            source = Path(attachment.uri)
            if source.exists():
                size = self._copy_local(source, destination)
            else:
                raise FileDownloadError(f"unsupported attachment uri: {attachment.uri}")
        return DownloadedFile(
            source_uri=attachment.uri,
            path=str(destination),
            name=name,
            size_bytes=size,
        )

    def _download_http(self, url: str, destination: Path) -> int:
        response = self._client.get(url)
        response.raise_for_status()
        size = int(response.headers.get("content-length") or 0)
        if size and size > self.max_bytes:
            raise FileDownloadError(f"file too large: {size} > {self.max_bytes}")
        data = response.content
        if len(data) > self.max_bytes:
            raise FileDownloadError(f"file too large: {len(data)} > {self.max_bytes}")
        destination.write_bytes(data)
        return len(data)

    def _copy_local(self, source: Path, destination: Path) -> int:
        if not source.exists() or not source.is_file():
            raise FileDownloadError(f"local file does not exist: {source}")
        size = source.stat().st_size
        if size > self.max_bytes:
            raise FileDownloadError(f"file too large: {size} > {self.max_bytes}")
        shutil.copyfile(source, destination)
        return size


def _safe_filename(name: str) -> str:
    value = Path(name).name.strip().replace("\x00", "")
    if not value or value in {".", ".."}:
        raise FileDownloadError("invalid attachment filename")
    return value
