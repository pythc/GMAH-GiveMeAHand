from pathlib import Path

import httpx
import pytest
from pydantic import SecretStr

from agent_workflow.channels.events import Attachment, AttachmentType
from agent_workflow.channels.onebot.client import OneBotClientError, OneBotHttpClient
from agent_workflow.channels.onebot.downloader import FileDownloadError, OneBotFileDownloader


def test_onebot_file_downloader_copies_local_file(tmp_path: Path) -> None:
    source = tmp_path / "source.zip"
    source.write_bytes(b"zipdata")
    downloader = OneBotFileDownloader(tmp_path / "downloads")
    result = downloader.download_attachment(
        Attachment(
            type=AttachmentType.FILE,
            mime="application/zip",
            uri=str(source),
            name="source.zip",
        )
    )

    assert result.size_bytes == len(b"zipdata")
    assert (tmp_path / "downloads" / "source.zip").exists()


def test_onebot_file_downloader_rejects_missing_and_large_files(tmp_path: Path) -> None:
    source = tmp_path / "large.zip"
    source.write_bytes(b"x" * 8)
    downloader = OneBotFileDownloader(tmp_path / "downloads", max_bytes=4)

    with pytest.raises(FileDownloadError):
        downloader.download_attachment(
            Attachment(
                type=AttachmentType.FILE,
                mime="application/zip",
                uri=str(source),
                name="large.zip",
            )
        )
    with pytest.raises(FileDownloadError):
        downloader.download_attachment(
            Attachment(
                type=AttachmentType.FILE,
                mime="application/zip",
                uri="missing.zip",
                name="missing.zip",
            )
        )


def test_onebot_file_downloader_downloads_http(tmp_path: Path) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=b"hello", headers={"content-length": "5"})

    downloader = OneBotFileDownloader(
        tmp_path / "downloads",
        client=httpx.Client(transport=httpx.MockTransport(handler)),
    )
    result = downloader.download_attachment(
        Attachment(
            type=AttachmentType.FILE,
            mime="application/zip",
            uri="https://files.test/project.zip",
            name="project.zip",
        )
    )

    assert result.size_bytes == 5


def test_onebot_http_client_sends_messages_and_handles_failures() -> None:
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request.url.path)
        if request.url.path.endswith("/send_private_msg"):
            return httpx.Response(200, json={"status": "failed", "wording": "blocked"})
        return httpx.Response(200, json={"status": "ok", "data": {"message_id": 1}})

    client = OneBotHttpClient(
        base_url="http://onebot.test",
        access_token=SecretStr("token"),
        client=httpx.Client(transport=httpx.MockTransport(handler)),
    )

    result = client.send_group_msg("123", "hello")
    assert result.response["status"] == "ok"
    assert "/send_group_msg" in calls
    with pytest.raises(OneBotClientError):
        client.send_private_msg("456", "hello")
