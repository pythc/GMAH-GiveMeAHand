"""Tests for OneBot WebSocket listener and event handler."""

import asyncio
import json
from unittest.mock import AsyncMock, patch

import pytest

from agent_workflow.channels.onebot.event_handler import OneBotEventHandler
from agent_workflow.channels.onebot.models import OneBotEvent
from agent_workflow.channels.onebot.ws_listener import (
    OneBotWsListener,
    WsConnectionState,
    WsListenerStatus,
)

# ---------------------------------------------------------------------------
# WsListener: state management
# ---------------------------------------------------------------------------


class TestWsListenerInit:
    def test_initial_state_is_disconnected(self) -> None:
        listener = OneBotWsListener(url="ws://localhost:3001/ws")
        assert listener.state == WsConnectionState.DISCONNECTED

    def test_url_stored(self) -> None:
        listener = OneBotWsListener(url="ws://example.com:6700")
        assert listener.url == "ws://example.com:6700"

    def test_status_returns_model(self) -> None:
        listener = OneBotWsListener(url="ws://localhost:3001/ws")
        status = listener.status()
        assert isinstance(status, WsListenerStatus)
        assert status.state == WsConnectionState.DISCONNECTED
        assert status.url == "ws://localhost:3001/ws"
        assert status.reconnect_attempts == 0
        assert status.total_events_received == 0


class TestWsListenerConnect:
    @pytest.mark.asyncio
    async def test_connect_changes_state(self) -> None:
        listener = OneBotWsListener(url="ws://localhost:3001/ws")
        mock_ws = AsyncMock()
        mock_ws.close = AsyncMock()

        with patch(
            "agent_workflow.channels.onebot.ws_listener.connect",
            new=AsyncMock(return_value=mock_ws),
        ):
            await listener.connect()
            assert listener.state == WsConnectionState.CONNECTED

    @pytest.mark.asyncio
    async def test_connect_when_already_connected_is_noop(self) -> None:
        listener = OneBotWsListener(url="ws://localhost:3001/ws")
        mock_ws = AsyncMock()
        mock_ws.close = AsyncMock()

        mock_connect = AsyncMock(return_value=mock_ws)
        with patch(
            "agent_workflow.channels.onebot.ws_listener.connect",
            new=mock_connect,
        ):
            await listener.connect()
            await listener.connect()
            # Should only call connect once
            assert mock_connect.call_count == 1

    @pytest.mark.asyncio
    async def test_disconnect_changes_state(self) -> None:
        listener = OneBotWsListener(url="ws://localhost:3001/ws")
        mock_ws = AsyncMock()
        mock_ws.close = AsyncMock()

        with patch(
            "agent_workflow.channels.onebot.ws_listener.connect",
            new=AsyncMock(return_value=mock_ws),
        ):
            await listener.connect()
            await listener.disconnect()
            assert listener.state == WsConnectionState.DISCONNECTED


# ---------------------------------------------------------------------------
# WsListener: reconnect logic
# ---------------------------------------------------------------------------


class TestWsListenerReconnect:
    @pytest.mark.asyncio
    async def test_reconnect_increments_attempts(self) -> None:
        listener = OneBotWsListener(
            url="ws://localhost:3001/ws",
            reconnect_max_seconds=2,
        )
        listener._should_run = True
        listener._state = WsConnectionState.CONNECTED

        # First call to _create_connection fails, second succeeds
        mock_ws = AsyncMock()
        mock_ws.close = AsyncMock()
        call_count = 0

        async def _fake_connect(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise OSError("Connection refused")
            return mock_ws

        with patch(
            "agent_workflow.channels.onebot.ws_listener.connect",
            side_effect=_fake_connect,
        ):
            await listener._reconnect()

        assert listener.state == WsConnectionState.CONNECTED
        # After successful reconnect, attempts reset to 0
        assert listener._reconnect_attempts == 0

    @pytest.mark.asyncio
    async def test_reconnect_stops_when_should_run_false(self) -> None:
        listener = OneBotWsListener(
            url="ws://localhost:3001/ws",
            reconnect_max_seconds=1,
        )
        listener._should_run = True
        listener._state = WsConnectionState.CONNECTED

        async def _fail_and_stop(*args, **kwargs):
            # After first attempt, mark should_run as False
            listener._should_run = False
            raise OSError("Connection refused")

        with patch(
            "agent_workflow.channels.onebot.ws_listener.connect",
            side_effect=_fail_and_stop,
        ):
            await listener._reconnect()

        assert listener.state == WsConnectionState.DISCONNECTED


# ---------------------------------------------------------------------------
# WsListener: message handling
# ---------------------------------------------------------------------------


class TestWsListenerMessageHandling:
    @pytest.mark.asyncio
    async def test_handle_message_parses_event(self) -> None:
        listener = OneBotWsListener(url="ws://localhost:3001/ws")
        callback = AsyncMock()

        event_data = {
            "time": 1700000000,
            "self_id": 12345,
            "post_type": "message",
            "message_type": "private",
            "user_id": 67890,
            "message": "hello",
            "raw_message": "hello",
        }
        raw = json.dumps(event_data)
        await listener._handle_message(raw, callback)

        callback.assert_called_once()
        event_arg = callback.call_args[0][0]
        assert isinstance(event_arg, OneBotEvent)
        assert event_arg.post_type == "message"
        assert event_arg.user_id == 67890

    @pytest.mark.asyncio
    async def test_handle_message_ignores_meta_event(self) -> None:
        listener = OneBotWsListener(url="ws://localhost:3001/ws")
        callback = AsyncMock()

        event_data = {
            "time": 1700000000,
            "post_type": "meta_event",
            "meta_event_type": "heartbeat",
            "self_id": 12345,
        }
        raw = json.dumps(event_data)
        await listener._handle_message(raw, callback)

        callback.assert_not_called()

    @pytest.mark.asyncio
    async def test_handle_message_ignores_invalid_json(self) -> None:
        listener = OneBotWsListener(url="ws://localhost:3001/ws")
        callback = AsyncMock()

        await listener._handle_message("not json at all", callback)
        callback.assert_not_called()

    @pytest.mark.asyncio
    async def test_handle_message_counts_events(self) -> None:
        listener = OneBotWsListener(url="ws://localhost:3001/ws")
        callback = AsyncMock()

        event_data = {
            "time": 1700000000,
            "self_id": 12345,
            "post_type": "message",
            "message_type": "group",
            "user_id": 111,
            "group_id": 222,
            "message": "test",
            "raw_message": "test",
        }
        raw = json.dumps(event_data)
        await listener._handle_message(raw, callback)
        await listener._handle_message(raw, callback)

        assert listener._total_events == 2


# ---------------------------------------------------------------------------
# EventHandler: queue and dispatch
# ---------------------------------------------------------------------------


class TestOneBotEventHandler:
    @pytest.mark.asyncio
    async def test_handle_event_enqueues(self) -> None:
        handler = OneBotEventHandler()
        event = OneBotEvent(
            time=1700000000,
            post_type="message",
            message_type="private",
            user_id=123,
            message="hi",
            raw_message="hi",
        )
        await handler.handle_event(event)
        assert handler.stats.total_received == 1
        assert handler._queue.qsize() == 1

    @pytest.mark.asyncio
    async def test_start_and_dispatch(self) -> None:
        callback = AsyncMock()
        handler = OneBotEventHandler(callbacks=[callback])

        event = OneBotEvent(
            time=1700000000,
            post_type="message",
            message_type="private",
            user_id=123,
            message="hello world",
            raw_message="hello world",
        )

        await handler.start()
        await handler.handle_event(event)

        # Give the processor a moment to consume
        await asyncio.sleep(0.05)

        callback.assert_called_once()
        normalized, raw_event = callback.call_args[0]
        assert normalized.channel == "qq"
        assert normalized.content.text == "hello world"
        assert raw_event.user_id == 123

        await handler.stop()

    @pytest.mark.asyncio
    async def test_non_normalizable_event_skipped(self) -> None:
        callback = AsyncMock()
        handler = OneBotEventHandler(callbacks=[callback])

        # meta_event cannot be normalized by the adapter
        event = OneBotEvent(
            time=1700000000,
            post_type="meta_event",
            meta_event_type="heartbeat",
        )

        await handler.start()
        await handler.handle_event(event)
        await asyncio.sleep(0.05)

        callback.assert_not_called()
        assert handler.stats.total_processed == 0

        await handler.stop()

    @pytest.mark.asyncio
    async def test_register_callback(self) -> None:
        handler = OneBotEventHandler()
        cb1 = AsyncMock()
        cb2 = AsyncMock()
        handler.register_callback(cb1)
        handler.register_callback(cb2)

        event = OneBotEvent(
            time=1700000000,
            post_type="message",
            message_type="private",
            user_id=456,
            message="test",
            raw_message="test",
        )

        await handler.start()
        await handler.handle_event(event)
        await asyncio.sleep(0.05)

        cb1.assert_called_once()
        cb2.assert_called_once()

        await handler.stop()

    @pytest.mark.asyncio
    async def test_queue_full_drops_event(self) -> None:
        handler = OneBotEventHandler(queue_max_size=1)
        event = OneBotEvent(
            time=1700000000,
            post_type="message",
            message_type="private",
            user_id=789,
            message="a",
            raw_message="a",
        )

        await handler.handle_event(event)
        await handler.handle_event(event)  # Should be dropped (queue full)

        assert handler.stats.total_received == 2
        assert handler._queue.qsize() == 1

    @pytest.mark.asyncio
    async def test_callback_error_does_not_crash_handler(self) -> None:
        async def failing_callback(normalized, raw_event):
            raise RuntimeError("oops")

        handler = OneBotEventHandler(callbacks=[failing_callback])

        event = OneBotEvent(
            time=1700000000,
            post_type="message",
            message_type="private",
            user_id=999,
            message="x",
            raw_message="x",
        )

        await handler.start()
        await handler.handle_event(event)
        await asyncio.sleep(0.05)

        assert handler.stats.total_errors == 1
        assert handler.stats.total_processed == 1

        await handler.stop()
