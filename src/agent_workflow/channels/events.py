"""Normalized event models for channel adapters."""

from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, Field


class AttachmentType(StrEnum):
    FILE = "file"
    IMAGE = "image"
    AUDIO = "audio"
    VIDEO = "video"


class Sender(BaseModel):
    user_id: str
    display_name: str | None = None
    role: str | None = None


class Attachment(BaseModel):
    type: AttachmentType
    mime: str
    uri: str
    name: str | None = None
    size_bytes: int | None = Field(default=None, ge=0)


class MessageContent(BaseModel):
    text: str | None = None
    attachments: list[Attachment] = Field(default_factory=list)


class NormalizedChannelEvent(BaseModel):
    channel: str
    platform_protocol: str
    conversation_id: str
    message_id: str
    sender: Sender
    content: MessageContent
    timestamp: datetime
