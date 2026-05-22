"""Channel-agnostic evaluation automation engine.

Extracts the common evaluation workflow logic from qq.py into a reusable engine
that works with any ChannelClient implementation. This is the "shared brain"
that decides what to do when a message arrives from any IM channel.

Inspired by cc-haha's approach where adapters/common/ provides shared logic
and each platform adapter only handles platform-specific I/O.
"""

from __future__ import annotations

import logging
import re
import threading
from collections import deque
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Callable

from pydantic import BaseModel

from .base import ChannelClient, ChannelSettings, split_message
from .events import NormalizedChannelEvent

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------

_URL_RE = re.compile(r"https?://[^\s\]）)>]+", re.IGNORECASE)
_TRIGGER_WORDS = ("课题", "评价", "评测", "分析", "报告", "论文", "项目", "仓库")


class AutomationResult(BaseModel):
    """Result of processing a single event."""

    action: str
    status: str  # "success", "failed", "skipped", "queued"
    detail: str | None = None
    reply: str | None = None


class EvaluationQueueItem(BaseModel):
    """Item waiting in the evaluation queue."""

    session_id: str
    conversation_id: str
    message_id: str | None
    source_url: str | None
    archive_path: str | None
    queued_at: str


# ---------------------------------------------------------------------------
# Automation Engine
# ---------------------------------------------------------------------------


class ChannelAutomationEngine:
    """Channel-agnostic evaluation automation logic.

    Handles:
    - URL detection → trigger evaluation
    - Archive detection → download + extract → evaluate
    - Admin LLM replies
    - Blacklist / trigger word filtering
    - PDF report generation and sending
    - Evaluation queue management (serial execution)
    - WebSocket progress broadcasting

    Usage:
        engine = ChannelAutomationEngine(client=onebot_client, settings=qq_settings)
        results = engine.handle_event(normalized_event)
    """

    def __init__(
        self,
        *,
        client: ChannelClient,
        settings: ChannelSettings,
        ws_broadcast: Callable[[dict[str, Any], str | None], None] | None = None,
    ) -> None:
        self.client = client
        self.settings = settings
        self._ws_broadcast = ws_broadcast
        # Evaluation queue (one at a time)
        self._queue: deque[EvaluationQueueItem] = deque(maxlen=20)
        self._active_session: str | None = None
        self._lock = threading.Lock()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def should_trigger_evaluation(self, event: NormalizedChannelEvent) -> bool:
        """Determine if this event should trigger an evaluation.

        Triggers on:
        - GitHub/URL in message text
        - Archive file attachment
        - Trigger keywords for admin users
        """
        if not self.settings.auto_evaluate_enabled:
            return False

        text = event.text or ""

        # URL detection
        if _URL_RE.search(text):
            return True

        # Archive attachment
        if event.attachments:
            for att in event.attachments:
                if att.filename and _is_archive_filename(att.filename):
                    return True

        # Trigger words (for admin users)
        if event.sender_id in self.settings.admin_users:
            return any(word in text for word in _TRIGGER_WORDS)

        # Non-admin needs URL or archive
        return False

    def is_admin(self, event: NormalizedChannelEvent) -> bool:
        """Check if the sender is an admin user."""
        return event.sender_id in self.settings.admin_users

    def is_blacklisted(self, event: NormalizedChannelEvent) -> bool:
        """Check if the sender is blacklisted."""
        return event.sender_id in self.settings.blacklist

    def extract_url(self, event: NormalizedChannelEvent) -> str | None:
        """Extract the first URL from the event text."""
        text = event.text or ""
        match = _URL_RE.search(text)
        return match.group(0) if match else None

    # ------------------------------------------------------------------
    # Message Sending (delegates to ChannelClient)
    # ------------------------------------------------------------------

    def send_reply(
        self, event: NormalizedChannelEvent, text: str
    ) -> AutomationResult:
        """Send a text reply, quoting the original message in groups."""
        try:
            self.client.send_message(
                event.conversation_id, text, reply_to=event.message_id
            )
            return AutomationResult(
                action="send_reply", status="success", reply=text
            )
        except Exception as exc:  # noqa: BLE001
            return AutomationResult(
                action="send_reply", status="failed", detail=str(exc)
            )

    def send_pdf_report(
        self, event: NormalizedChannelEvent, markdown_text: str
    ) -> AutomationResult:
        """Generate PDF from evaluation markdown and send as file."""
        try:
            from agent_workflow.evaluation.pdf_report import generate_evaluation_pdf

            timestamp = datetime.now(UTC).strftime("%Y%m%d_%H%M%S")
            filename = f"课题评测报告_{timestamp}.pdf"
            pdf_path = generate_evaluation_pdf(markdown_text, filename)
            pdf_data = pdf_path.read_bytes()

            self.client.send_file(event.conversation_id, pdf_data, filename)
            return AutomationResult(
                action="send_pdf",
                status="success",
                detail=f"PDF sent: {filename} ({len(pdf_data)} bytes)",
            )
        except Exception as exc:  # noqa: BLE001
            # Fallback: send text if PDF fails
            logger.error("PDF generation/send failed: %s", exc)
            self.send_reply(event, f"评测完成，但 PDF 发送失败：{exc}")
            return AutomationResult(
                action="send_pdf", status="failed", detail=str(exc)
            )

    def send_progress(
        self, event: NormalizedChannelEvent, message: str, session_id: str | None = None
    ) -> None:
        """Send a progress update to IM + broadcast via WebSocket."""
        # Send to IM channel
        if self.settings.auto_reply_enabled:
            self.client.send_message(event.conversation_id, message)

        # Broadcast to WebSocket subscribers
        if self._ws_broadcast:
            self._ws_broadcast(
                {
                    "type": "progress",
                    "session_id": session_id or "",
                    "message": message,
                    "timestamp": datetime.now(UTC).isoformat(),
                },
                session_id,
            )

    # ------------------------------------------------------------------
    # Queue Management
    # ------------------------------------------------------------------

    def enqueue_evaluation(
        self,
        event: NormalizedChannelEvent,
        source_url: str | None = None,
        archive_path: str | None = None,
    ) -> tuple[str, bool]:
        """Add an evaluation to the queue. Returns (session_id, is_immediate).

        If no evaluation is active, starts immediately (is_immediate=True).
        Otherwise queues it (is_immediate=False).
        """
        from uuid import uuid4

        session_id = uuid4().hex[:12]
        item = EvaluationQueueItem(
            session_id=session_id,
            conversation_id=event.conversation_id,
            message_id=event.message_id,
            source_url=source_url,
            archive_path=archive_path,
            queued_at=datetime.now(UTC).isoformat(),
        )

        with self._lock:
            if self._active_session is None:
                self._active_session = session_id
                return session_id, True
            self._queue.append(item)
            return session_id, False

    def complete_evaluation(self, session_id: str) -> None:
        """Mark an evaluation as complete, allow next in queue."""
        with self._lock:
            if self._active_session == session_id:
                self._active_session = None

    def get_next_queued(self) -> EvaluationQueueItem | None:
        """Pop the next queued evaluation item."""
        with self._lock:
            if self._queue:
                item = self._queue.popleft()
                self._active_session = item.session_id
                return item
            return None

    @property
    def queue_length(self) -> int:
        return len(self._queue)

    @property
    def is_evaluating(self) -> bool:
        return self._active_session is not None


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _is_archive_filename(filename: str) -> bool:
    """Check if a filename looks like an archive."""
    lower = filename.lower()
    return any(
        lower.endswith(ext)
        for ext in (".zip", ".tar.gz", ".tgz", ".tar.bz2", ".rar", ".7z")
    )
