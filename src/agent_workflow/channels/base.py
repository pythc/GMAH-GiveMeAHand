"""Abstract base classes for multi-channel IM integration.

Defines the interfaces that any IM channel (QQ/OneBot, WeChat, Feishu, DingTalk)
must implement. Inspired by cc-haha's adapters/common/ architecture.

Usage:
    from agent_workflow.channels.base import ChannelClient, ChannelAdapter

    class WeChatClient(ChannelClient):
        def send_message(self, conversation_id, text, reply_to=None):
            ...
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from pydantic import BaseModel

from .events import NormalizedChannelEvent


class ChannelClient(ABC):
    """Abstract IM client — sends messages and files to a conversation.

    Each channel (QQ, WeChat, Feishu) implements this interface.
    The conversation_id format is channel-specific but uses a prefix convention:
    - "group:{id}" for group chats
    - "private:{id}" for direct messages
    """

    @abstractmethod
    def send_message(
        self, conversation_id: str, text: str, reply_to: str | None = None
    ) -> Any:
        """Send a text message to a conversation.

        Args:
            conversation_id: Target conversation (e.g., "group:123456")
            text: Message text content
            reply_to: Optional message ID to quote/reply to
        """

    @abstractmethod
    def send_file(
        self, conversation_id: str, data: bytes, filename: str
    ) -> Any:
        """Send a file to a conversation.

        Args:
            conversation_id: Target conversation
            data: File content as bytes
            filename: Display filename
        """

    def send_message_split(
        self, conversation_id: str, text: str, max_length: int = 2000, reply_to: str | None = None
    ) -> list[Any]:
        """Send a long message, splitting into chunks if needed.

        Default implementation splits by paragraph > line > space > hard cut.
        Channels can override for platform-specific limits.
        """
        chunks = split_message(text, max_length)
        results = []
        for i, chunk in enumerate(chunks):
            # Only reply_to the first chunk
            results.append(self.send_message(
                conversation_id, chunk, reply_to=reply_to if i == 0 else None
            ))
        return results


class ChannelAdapter(ABC):
    """Normalizes platform-specific events into NormalizedChannelEvent.

    Each channel implements this to convert its webhook payload into
    the universal event format.
    """

    @property
    @abstractmethod
    def channel_name(self) -> str:
        """Return the channel identifier (e.g., 'qq', 'wechat', 'feishu')."""

    @abstractmethod
    def normalize(self, raw_event: dict[str, Any]) -> NormalizedChannelEvent | None:
        """Convert a raw platform event to NormalizedChannelEvent.

        Returns None if the event cannot be normalized (e.g., heartbeat, system event).
        """

    def is_self_message(self, raw_event: dict[str, Any]) -> bool:
        """Check if the event is from the bot itself (to prevent loops).

        Default returns False. Channels should override for their specific logic.
        """
        return False


class ChannelSettings(BaseModel):
    """Base settings for any IM channel."""

    channel_name: str
    enabled: bool = True
    auto_evaluate_enabled: bool = True
    auto_reply_enabled: bool = True
    admin_users: list[str] = []  # User IDs with admin privileges
    blacklist: list[str] = []  # Blocked user IDs


class ChannelInfo(BaseModel):
    """Metadata about a registered channel."""

    name: str
    display_name: str
    connected: bool = False
    status: str = "registered"


# ---------------------------------------------------------------------------
# Utility functions (shared by all channels, like cc-haha's format.ts)
# ---------------------------------------------------------------------------


def split_message(text: str, max_length: int = 2000) -> list[str]:
    """Split long text into chunks respecting paragraph/line boundaries.

    Inspired by cc-haha's adapters/common/format.ts splitMessage().
    """
    if len(text) <= max_length:
        return [text]

    chunks: list[str] = []
    remaining = text

    while remaining:
        if len(remaining) <= max_length:
            chunks.append(remaining)
            break

        # Try to split at paragraph boundary
        split_at = remaining.rfind("\n\n", 0, max_length)
        if split_at <= 0:
            split_at = remaining.rfind("\n", 0, max_length)
        if split_at <= 0:
            split_at = remaining.rfind(". ", 0, max_length)
        if split_at <= 0:
            split_at = remaining.rfind(" ", 0, max_length)
        if split_at <= 0:
            split_at = max_length

        # Include delimiter for paragraph/sentence breaks
        if split_at < len(remaining) and remaining[split_at] in ("\n", "."):
            split_at += 1

        chunks.append(remaining[:split_at].rstrip())
        remaining = remaining[split_at:].lstrip()

    return chunks
