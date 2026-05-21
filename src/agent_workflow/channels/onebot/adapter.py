"""Normalize OneBot/NapCat events into internal channel events."""

from datetime import UTC, datetime
from mimetypes import guess_type
from pathlib import Path
from typing import Any

from agent_workflow.channels.events import (
    Attachment,
    AttachmentType,
    MessageContent,
    NormalizedChannelEvent,
    Sender,
)
from agent_workflow.channels.onebot.models import OneBotEvent, OneBotMessageSegment


class OneBotAdapterError(ValueError):
    """Raised when a OneBot event cannot be normalized."""


class OneBotAdapter:
    """Convert OneBot v11 message and file events into normalized events."""

    def normalize(self, event: OneBotEvent) -> NormalizedChannelEvent:
        if event.post_type in {"message", "message_sent"}:
            return self._normalize_message(event)
        if event.post_type == "notice" and event.notice_type == "group_upload":
            return self._normalize_group_upload(event)
        raise OneBotAdapterError(f"unsupported OneBot event: {event.post_type}/{event.notice_type}")

    def _normalize_message(self, event: OneBotEvent) -> NormalizedChannelEvent:
        text, attachments = _parse_message(event.message)
        return NormalizedChannelEvent(
            channel="qq",
            platform_protocol="onebot_v11",
            conversation_id=_conversation_id(event),
            message_id=str(event.message_id or f"onebot:{event.time}:{event.user_id}"),
            sender=_sender(event),
            content=MessageContent(text=text or event.raw_message, attachments=attachments),
            timestamp=_timestamp(event.time),
        )

    def _normalize_group_upload(self, event: OneBotEvent) -> NormalizedChannelEvent:
        if event.file is None:
            raise OneBotAdapterError("group_upload event requires file payload")
        attachment = _attachment_from_data(event.file.model_dump(exclude_none=True))
        return NormalizedChannelEvent(
            channel="qq",
            platform_protocol="onebot_v11",
            conversation_id=_conversation_id(event),
            message_id=str(event.file.id or f"group_upload:{event.time}:{event.user_id}"),
            sender=_sender(event),
            content=MessageContent(text=f"上传文件：{attachment.name}", attachments=[attachment]),
            timestamp=_timestamp(event.time),
        )


def _parse_message(
    message: str | list[OneBotMessageSegment] | None,
) -> tuple[str | None, list[Attachment]]:
    if message is None:
        return None, []
    if isinstance(message, str):
        return message, []

    texts: list[str] = []
    attachments: list[Attachment] = []
    for segment in message:
        if segment.type == "text":
            text = segment.data.get("text")
            if isinstance(text, str):
                texts.append(text)
        elif segment.type == "at":
            # Preserve @mention QQ number in text for trigger matching
            qq = segment.data.get("qq") or segment.data.get("id") or ""
            texts.append(f"@{qq}")
        elif segment.type in {"file", "image", "record", "video"}:
            attachments.append(_attachment_from_data(segment.data, segment_type=segment.type))
    return "".join(texts).strip() or None, attachments


def _attachment_from_data(data: dict[str, Any], segment_type: str = "file") -> Attachment:
    name = _first_str(data, "name", "file", "filename") or "unnamed"
    uri = _first_str(data, "url", "path", "file", "file_id", "id") or name
    mime = _mime_for(name, segment_type)
    size = data.get("size")
    return Attachment(
        type=_attachment_type(segment_type, name),
        mime=mime,
        uri=uri,
        name=name,
        size_bytes=size if isinstance(size, int) else None,
    )


def _first_str(data: dict[str, Any], *keys: str) -> str | None:
    for key in keys:
        value = data.get(key)
        if isinstance(value, str) and value:
            return value
    return None


def _attachment_type(segment_type: str, name: str) -> AttachmentType:
    if segment_type == "image":
        return AttachmentType.IMAGE
    if segment_type == "record":
        return AttachmentType.AUDIO
    if segment_type == "video":
        return AttachmentType.VIDEO
    mime = guess_type(name)[0] or "application/octet-stream"
    if mime.startswith("image/"):
        return AttachmentType.IMAGE
    if mime.startswith("audio/"):
        return AttachmentType.AUDIO
    if mime.startswith("video/"):
        return AttachmentType.VIDEO
    return AttachmentType.FILE


def _mime_for(name: str, segment_type: str) -> str:
    if segment_type == "record":
        return "audio/unknown"
    guessed = guess_type(name)[0]
    return guessed or "application/octet-stream"


def _conversation_id(event: OneBotEvent) -> str:
    if event.group_id is not None:
        return f"group:{event.group_id}"
    if event.user_id is not None:
        return f"private:{event.user_id}"
    return "unknown"


def _sender(event: OneBotEvent) -> Sender:
    sender = event.sender
    display_name = None
    role = None
    if sender is not None:
        display_name = sender.card or sender.nickname
        role = sender.role
    return Sender(user_id=str(event.user_id or "unknown"), display_name=display_name, role=role)


def _timestamp(value: int | float | None) -> datetime:
    if value is None:
        return datetime.now(UTC)
    return datetime.fromtimestamp(float(value), tz=UTC)


def is_archive_attachment(attachment: Attachment) -> bool:
    suffixes = [suffix.lower() for suffix in Path(attachment.name or attachment.uri).suffixes]
    return suffixes[-2:] == [".tar", ".gz"] or bool(
        suffixes and suffixes[-1] in {".zip", ".7z", ".rar", ".tar", ".gz", ".tgz"}
    )
