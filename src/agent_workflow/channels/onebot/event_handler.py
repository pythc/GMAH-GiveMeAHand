"""Event handler for OneBot events with auto-action dispatch."""

import asyncio
import logging
from collections.abc import Awaitable, Callable

from pydantic import BaseModel

from agent_workflow.channels.events import NormalizedChannelEvent
from agent_workflow.channels.onebot.adapter import OneBotAdapter
from agent_workflow.channels.onebot.models import OneBotEvent

logger = logging.getLogger(__name__)


class EventHandlerStats(BaseModel):
    """Runtime statistics for the event handler."""

    total_received: int = 0
    total_processed: int = 0
    total_errors: int = 0
    queue_size: int = 0


class OneBotEventHandler:
    """Receives OneBot events, normalizes them, and dispatches to registered callbacks.

    This handler manages an internal async queue so that event production
    (from WebSocket or webhook) is decoupled from processing. Callbacks are
    invoked sequentially per event to preserve ordering.
    """

    def __init__(
        self,
        *,
        queue_max_size: int = 1000,
        callbacks: list[Callable[[NormalizedChannelEvent, OneBotEvent], Awaitable[None]]]
        | None = None,
    ) -> None:
        self._adapter = OneBotAdapter()
        self._queue: asyncio.Queue[OneBotEvent] = asyncio.Queue(maxsize=queue_max_size)
        self._callbacks: list[
            Callable[[NormalizedChannelEvent, OneBotEvent], Awaitable[None]]
        ] = list(callbacks or [])
        self._processor_task: asyncio.Task[None] | None = None
        self._stats = EventHandlerStats()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    @property
    def stats(self) -> EventHandlerStats:
        self._stats.queue_size = self._queue.qsize()
        return self._stats.model_copy()

    def register_callback(
        self,
        callback: Callable[[NormalizedChannelEvent, OneBotEvent], Awaitable[None]],
    ) -> None:
        """Register an additional processing callback."""
        self._callbacks.append(callback)

    async def handle_event(self, event: OneBotEvent) -> None:
        """Enqueue a raw OneBot event for async processing.

        This is the entry point called by the WebSocket listener or webhook.
        """
        self._stats.total_received += 1
        try:
            self._queue.put_nowait(event)
        except asyncio.QueueFull:
            logger.warning("Event queue full, dropping event")

    async def start(self) -> None:
        """Start the background event processing loop."""
        if self._processor_task is not None and not self._processor_task.done():
            return
        self._processor_task = asyncio.create_task(
            self._process_loop(),
            name="onebot-event-processor",
        )

    async def stop(self) -> None:
        """Stop the background processor and drain remaining events."""
        if self._processor_task is not None and not self._processor_task.done():
            self._processor_task.cancel()
            try:
                await self._processor_task
            except asyncio.CancelledError:
                pass
            self._processor_task = None

    # ------------------------------------------------------------------
    # Internal processing
    # ------------------------------------------------------------------

    async def _process_loop(self) -> None:
        """Continuously dequeue and process events."""
        while True:
            try:
                event = await self._queue.get()
                await self._dispatch(event)
                self._queue.task_done()
            except asyncio.CancelledError:
                break
            except Exception as exc:  # noqa: BLE001
                logger.error("Error processing event: %s", exc)
                self._stats.total_errors += 1

    async def _dispatch(self, event: OneBotEvent) -> None:
        """Normalize and dispatch to all callbacks."""
        try:
            normalized = self._adapter.normalize(event)
        except Exception as exc:  # noqa: BLE001
            logger.debug("Skipping non-normalizable event: %s", exc)
            return

        self._stats.total_processed += 1

        for callback in self._callbacks:
            try:
                await callback(normalized, event)
            except Exception as exc:  # noqa: BLE001
                logger.error("Callback error: %s", exc)
                self._stats.total_errors += 1
