"""Channel registry — factory pattern for multi-IM support.

Provides a global registry where channel implementations register themselves.
The automation engine and API routes look up channels by name.

Usage:
    from agent_workflow.channels.registry import channel_registry

    # Register (typically in channels/onebot/__init__.py)
    channel_registry.register("qq", adapter=OneBotAdapter(), client_factory=make_client)

    # Lookup (in automation engine or routes)
    client = channel_registry.get_client("qq", base_url="...", access_token="...")
    adapter = channel_registry.get_adapter("qq")
"""

from __future__ import annotations

import logging
from typing import Any, Callable

from .base import ChannelAdapter, ChannelClient, ChannelInfo

logger = logging.getLogger(__name__)


class ChannelRegistry:
    """Central registry for all IM channel implementations."""

    def __init__(self) -> None:
        self._adapters: dict[str, ChannelAdapter] = {}
        self._client_factories: dict[str, Callable[..., ChannelClient]] = {}
        self._info: dict[str, ChannelInfo] = {}

    def register(
        self,
        name: str,
        *,
        adapter: ChannelAdapter,
        client_factory: Callable[..., ChannelClient],
        display_name: str | None = None,
    ) -> None:
        """Register a channel implementation.

        Args:
            name: Channel identifier (e.g., "qq", "wechat", "feishu")
            adapter: Instance that normalizes raw events
            client_factory: Callable that creates a ChannelClient with **kwargs
            display_name: Human-readable name (defaults to name)
        """
        self._adapters[name] = adapter
        self._client_factories[name] = client_factory
        self._info[name] = ChannelInfo(
            name=name,
            display_name=display_name or name.upper(),
        )
        logger.info("Channel registered: %s (%s)", name, display_name or name)

    def get_adapter(self, name: str) -> ChannelAdapter:
        """Get the adapter for a channel. Raises KeyError if not registered."""
        if name not in self._adapters:
            raise KeyError(f"Channel '{name}' not registered. Available: {list(self._adapters)}")
        return self._adapters[name]

    def get_client(self, name: str, **kwargs: Any) -> ChannelClient:
        """Create a client for a channel using its registered factory.

        Passes **kwargs to the factory (e.g., base_url, access_token).
        """
        if name not in self._client_factories:
            raise KeyError(f"Channel '{name}' not registered. Available: {list(self._client_factories)}")
        return self._client_factories[name](**kwargs)

    def list_channels(self) -> list[ChannelInfo]:
        """List all registered channels with their info."""
        return list(self._info.values())

    def has_channel(self, name: str) -> bool:
        """Check if a channel is registered."""
        return name in self._adapters

    def update_status(self, name: str, *, connected: bool | None = None, status: str | None = None) -> None:
        """Update connection status for a channel."""
        if name in self._info:
            if connected is not None:
                self._info[name].connected = connected
            if status is not None:
                self._info[name].status = status

    @property
    def channel_names(self) -> list[str]:
        return list(self._adapters.keys())


# Global singleton
channel_registry = ChannelRegistry()
