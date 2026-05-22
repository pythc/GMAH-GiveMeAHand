"""WebSocket connection manager for real-time evaluation progress.

Provides a global ConnectionManager that broadcasts evaluation events
(progress, tool calls, model responses, completion) to connected frontend
clients. Inspired by cc-haha's adapters/common/ws-bridge.ts architecture.
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

from fastapi import WebSocket, WebSocketDisconnect

logger = logging.getLogger(__name__)


class ConnectionManager:
    """Manage WebSocket connections with session-based subscriptions.

    Clients can:
    - Connect without session_id → receive ALL events (global subscriber)
    - Connect with session_id → receive only events for that session
    - Send {"type": "subscribe", "session_id": "..."} → add subscription
    - Send {"type": "ping"} → receive {"type": "pong"}
    """

    def __init__(self) -> None:
        # All connected WebSockets (for global broadcast)
        self._global: list[WebSocket] = []
        # session_id → list of WebSockets subscribed to that session
        self._subscriptions: dict[str, list[WebSocket]] = {}
        self._lock = asyncio.Lock()

    async def connect(self, ws: WebSocket, session_id: str | None = None) -> None:
        """Accept a new WebSocket connection."""
        await ws.accept()
        async with self._lock:
            self._global.append(ws)
            if session_id:
                self._subscriptions.setdefault(session_id, []).append(ws)
        logger.info(
            "WS connected (total=%d, session=%s)", len(self._global), session_id or "global"
        )

    async def disconnect(self, ws: WebSocket) -> None:
        """Remove a WebSocket from all tracking."""
        async with self._lock:
            if ws in self._global:
                self._global.remove(ws)
            for subs in self._subscriptions.values():
                if ws in subs:
                    subs.remove(ws)
        logger.debug("WS disconnected (remaining=%d)", len(self._global))

    async def subscribe(self, ws: WebSocket, session_id: str) -> None:
        """Subscribe a connected WebSocket to a specific session."""
        async with self._lock:
            self._subscriptions.setdefault(session_id, []).append(ws)

    async def broadcast(self, event: dict[str, Any], session_id: str | None = None) -> None:
        """Broadcast an event to relevant WebSocket clients.

        If session_id is provided, sends to:
        - All clients subscribed to that session
        - All global clients (those connected without a session filter)

        If session_id is None, sends to all global clients only.
        """
        async with self._lock:
            targets: set[WebSocket] = set()
            # Session-specific subscribers
            if session_id and session_id in self._subscriptions:
                targets.update(self._subscriptions[session_id])
            # Global subscribers (connected without session_id filter)
            # We treat all connections as global by default
            targets.update(self._global)

        dead: list[WebSocket] = []
        for ws in targets:
            try:
                await ws.send_json(event)
            except Exception:  # noqa: BLE001
                dead.append(ws)

        # Clean up dead connections
        for ws in dead:
            await self.disconnect(ws)

    def broadcast_sync(self, event: dict[str, Any], session_id: str | None = None) -> None:
        """Fire-and-forget broadcast from synchronous code.

        Schedules the async broadcast on the running event loop.
        Safe to call from threads (e.g., evaluation background worker).
        """
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                loop.create_task(self.broadcast(event, session_id))
            else:
                asyncio.run(self.broadcast(event, session_id))
        except RuntimeError:
            # No event loop available (e.g., during shutdown)
            pass

    @property
    def connection_count(self) -> int:
        return len(self._global)


# Global singleton — imported by other modules
ws_manager = ConnectionManager()


async def websocket_evaluation_endpoint(websocket: WebSocket) -> None:
    """FastAPI WebSocket endpoint handler for /ws/evaluation.

    Query params:
    - session_id (optional): subscribe to a specific evaluation session

    Client messages:
    - {"type": "ping"} → responds with {"type": "pong"}
    - {"type": "subscribe", "session_id": "..."} → adds session subscription
    """
    # Extract session_id from query params
    session_id = websocket.query_params.get("session_id")
    await ws_manager.connect(websocket, session_id)

    try:
        # Send connection confirmation
        await websocket.send_json({
            "type": "connected",
            "session_id": session_id,
            "message": "WebSocket connected successfully",
        })

        while True:
            raw = await websocket.receive_text()
            try:
                msg = json.loads(raw)
            except (json.JSONDecodeError, ValueError):
                await websocket.send_json({"type": "error", "message": "invalid JSON"})
                continue

            msg_type = msg.get("type")

            if msg_type == "ping":
                await websocket.send_json({"type": "pong"})

            elif msg_type == "subscribe":
                sub_session = msg.get("session_id")
                if sub_session:
                    await ws_manager.subscribe(websocket, sub_session)
                    await websocket.send_json({
                        "type": "subscribed",
                        "session_id": sub_session,
                    })
                else:
                    await websocket.send_json({
                        "type": "error",
                        "message": "subscribe requires session_id",
                    })

            else:
                await websocket.send_json({
                    "type": "error",
                    "message": f"unknown message type: {msg_type}",
                })

    except WebSocketDisconnect:
        await ws_manager.disconnect(websocket)
    except Exception:  # noqa: BLE001
        await ws_manager.disconnect(websocket)
