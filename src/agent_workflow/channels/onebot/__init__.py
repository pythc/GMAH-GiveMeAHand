"""OneBot/NapCat channel adapter."""

from agent_workflow.channels.onebot.adapter import OneBotAdapter
from agent_workflow.channels.onebot.client import OneBotHttpClient
from agent_workflow.channels.onebot.event_handler import OneBotEventHandler
from agent_workflow.channels.onebot.models import OneBotEvent
from agent_workflow.channels.onebot.ws_listener import OneBotWsListener

__all__ = [
    "OneBotAdapter",
    "OneBotEvent",
    "OneBotEventHandler",
    "OneBotHttpClient",
    "OneBotWsListener",
]


def _onebot_client_factory(**kwargs) -> OneBotHttpClient:  # type: ignore[type-arg]
    """Factory to create OneBotHttpClient for the channel registry."""
    from pydantic import SecretStr

    base_url = kwargs.get("base_url", "http://127.0.0.1:3001")
    token = kwargs.get("access_token")
    access_token = SecretStr(token) if token else None
    return OneBotHttpClient(base_url=base_url, access_token=access_token)


def register_onebot_channel() -> None:
    """Register QQ/OneBot as a channel in the global registry."""
    from agent_workflow.channels.registry import channel_registry

    channel_registry.register(
        "qq",
        adapter=OneBotAdapter(),
        client_factory=_onebot_client_factory,
        display_name="QQ (OneBot)",
    )

