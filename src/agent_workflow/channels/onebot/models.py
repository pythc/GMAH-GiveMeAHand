"""OneBot v11 event models used by NapCat/Lagrange adapters."""

from typing import Any, Literal

from pydantic import BaseModel, Field

OneBotPostType = Literal["message", "message_sent", "notice", "request", "meta_event"]


class OneBotSender(BaseModel):
    user_id: int | str | None = None
    nickname: str | None = None
    card: str | None = None
    role: str | None = None


class OneBotMessageSegment(BaseModel):
    type: str
    data: dict[str, Any] = Field(default_factory=dict)


class OneBotFileInfo(BaseModel):
    id: str | None = None
    name: str | None = None
    size: int | None = Field(default=None, ge=0)
    busid: int | None = None
    url: str | None = None
    path: str | None = None


class OneBotEvent(BaseModel):
    time: int | float | None = None
    self_id: int | str | None = None
    post_type: OneBotPostType
    message_type: str | None = None
    notice_type: str | None = None
    sub_type: str | None = None
    message_id: int | str | None = None
    user_id: int | str | None = None
    group_id: int | str | None = None
    sender: OneBotSender | None = None
    message: str | list[OneBotMessageSegment] | None = None
    raw_message: str | None = None
    file: OneBotFileInfo | None = None
    meta_event_type: str | None = None
