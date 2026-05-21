"""WebSocket listener for OneBot/NapCat forward WebSocket connections."""

import asyncio
import json
import logging
from collections.abc import Awaitable, Callable
from enum import StrEnum

from pydantic import BaseModel

from agent_workflow.channels.onebot.models import OneBotEvent

try:
    import websockets
    from websockets.asyncio.client import ClientConnection, connect
except ImportError as _import_err:
    raise ImportError(
        "websockets>=12.0 is required for WebSocket listener. "
        "Install it with: pip install 'websockets>=12.0'"
    ) from _import_err

logger = logging.getLogger(__name__)


class WsConnectionState(StrEnum):
    """WebSocket connection state."""

    DISCONNECTED = "disconnected"
    CONNECTING = "connecting"
    CONNECTED = "connected"
    RECONNECTING = "reconnecting"
    CLOSING = "closing"


class WsListenerStatus(BaseModel):
    """Snapshot of listener status for API responses."""

    state: WsConnectionState
    url: str
    reconnect_attempts: int = 0
    last_event_time: float | None = None
    total_events_received: int = 0


class OneBotWsListener:
    """WebSocket client that connects to a OneBot v11 forward WS endpoint.

    Supports automatic reconnection with exponential back-off and
    transparent heartbeat handling for meta_event/lifecycle events.
    """

    def __init__(
        self,
        url: str,
        access_token: str | None = None,
        reconnect_max_seconds: int = 60,
    ) -> None:
        self._url = url
        self._access_token = access_token
        self._reconnect_max_seconds = max(1, reconnect_max_seconds)

        self._state: WsConnectionState = WsConnectionState.DISCONNECTED
        self._ws: ClientConnection | None = None
        self._listen_task: asyncio.Task[None] | None = None
        self._reconnect_attempts: int = 0
        self._last_event_time: float | None = None
        self._total_events: int = 0
        self._should_run: bool = False

    # ------------------------------------------------------------------
    # Public properties
    # ------------------------------------------------------------------

    @property
    def state(self) -> WsConnectionState:
        return self._state

    @property
    def url(self) -> str:
        return self._url

    def status(self) -> WsListenerStatus:
        return WsListenerStatus(
            state=self._state,
            url=self._url,
            reconnect_attempts=self._reconnect_attempts,
            last_event_time=self._last_event_time,
            total_events_received=self._total_events,
        )

    # ------------------------------------------------------------------
    # Connection lifecycle
    # ------------------------------------------------------------------

    async def connect(self) -> None:
        """Establish the WebSocket connection (does not start listening)."""
        if self._state in {WsConnectionState.CONNECTED, WsConnectionState.CONNECTING}:
            logger.warning("WS listener already connected or connecting")
            return

        self._should_run = True
        self._state = WsConnectionState.CONNECTING
        self._ws = await self._create_connection()
        self._state = WsConnectionState.CONNECTED
        self._reconnect_attempts = 0
        logger.info("WebSocket connected to %s", self._url)

    async def listen(
        self,
        callback: Callable[[OneBotEvent], Awaitable[None]],
    ) -> None:
        """Start the background listener loop.

        This method spawns a background task that continuously reads messages
        from the WebSocket and invokes *callback* for each parsed event.
        The task handles reconnection automatically.
        """
        if self._listen_task is not None and not self._listen_task.done():
            logger.warning("Listener already running")
            return

        self._should_run = True
        if self._state != WsConnectionState.CONNECTED:
            await self.connect()

        self._listen_task = asyncio.create_task(
            self._listen_loop(callback),
            name="onebot-ws-listener",
        )

    async def disconnect(self) -> None:
        """Gracefully close the WebSocket connection and stop listening."""
        self._should_run = False
        self._state = WsConnectionState.CLOSING

        if self._listen_task is not None and not self._listen_task.done():
            self._listen_task.cancel()
            try:
                await self._listen_task
            except asyncio.CancelledError:
                pass
            self._listen_task = None

        await self._close_ws()
        self._state = WsConnectionState.DISCONNECTED
        logger.info("WebSocket disconnected from %s", self._url)

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    async def _create_connection(self) -> ClientConnection:
        """Create a new websockets client connection."""
        extra_headers: dict[str, str] = {}
        if self._access_token:
            extra_headers["Authorization"] = f"Bearer {self._access_token}"

        return await connect(
            self._url,
            additional_headers=extra_headers,
            open_timeout=10,
            close_timeout=5,
        )

    async def _close_ws(self) -> None:
        if self._ws is not None:
            try:
                await self._ws.close()
            except Exception:  # noqa: BLE001
                pass
            self._ws = None

    async def _listen_loop(
        self,
        callback: Callable[[OneBotEvent], Awaitable[None]],
    ) -> None:
        """Main loop: read messages, parse events, and auto-reconnect."""
        while self._should_run:
            try:
                await self._read_messages(callback)
            except asyncio.CancelledError:
                break
            except (
                websockets.exceptions.ConnectionClosed,
                websockets.exceptions.ConnectionClosedError,
                OSError,
            ) as exc:
                if not self._should_run:
                    break
                logger.warning("WS connection lost: %s", exc)
                await self._reconnect()
            except Exception as exc:  # noqa: BLE001
                if not self._should_run:
                    break
                logger.error("Unexpected error in WS listener: %s", exc)
                await self._reconnect()

    async def _read_messages(
        self,
        callback: Callable[[OneBotEvent], Awaitable[None]],
    ) -> None:
        """Read messages from the websocket until disconnected."""
        if self._ws is None:
            return
        async for raw_message in self._ws:
            if not self._should_run:
                break
            await self._handle_message(raw_message, callback)

    async def _handle_message(
        self,
        raw: str | bytes,
        callback: Callable[[OneBotEvent], Awaitable[None]],
    ) -> None:
        """Parse a single WebSocket message and dispatch."""
        text = raw if isinstance(raw, str) else raw.decode("utf-8", errors="replace")
        try:
            data = json.loads(text)
        except json.JSONDecodeError:
            logger.debug("Non-JSON WS message ignored: %s", text[:200])
            return

        if not isinstance(data, dict):
            return

        # Handle heartbeat / lifecycle meta events silently
        post_type = data.get("post_type")
        if post_type == "meta_event":
            meta_type = data.get("meta_event_type")
            logger.debug("Heartbeat/meta event: %s", meta_type)
            return

        try:
            event = OneBotEvent.model_validate(data)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Failed to parse OneBot event: %s", exc)
            return

        self._total_events += 1
        loop = asyncio.get_event_loop()
        self._last_event_time = loop.time()

        try:
            await callback(event)
        except Exception as exc:  # noqa: BLE001
            logger.error("Event callback error: %s", exc)

    async def _reconnect(self) -> None:
        """Reconnect with exponential back-off."""
        self._state = WsConnectionState.RECONNECTING
        await self._close_ws()

        while self._should_run:
            self._reconnect_attempts += 1
            delay = min(
                2 ** min(self._reconnect_attempts, 10),
                self._reconnect_max_seconds,
            )
            logger.info(
                "Reconnecting in %.1fs (attempt %d)...",
                delay,
                self._reconnect_attempts,
            )
            await asyncio.sleep(delay)

            if not self._should_run:
                break

            try:
                self._state = WsConnectionState.CONNECTING
                self._ws = await self._create_connection()
                self._state = WsConnectionState.CONNECTED
                self._reconnect_attempts = 0
                logger.info("Reconnected to %s", self._url)
                return
            except Exception as exc:  # noqa: BLE001
                logger.warning("Reconnection failed: %s", exc)

        self._state = WsConnectionState.DISCONNECTED
