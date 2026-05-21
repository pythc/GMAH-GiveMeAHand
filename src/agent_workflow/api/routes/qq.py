"""QQ/NapCat OneBot integration routes."""

import os
import re
import threading
from collections import deque
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

from fastapi import APIRouter, Request
from pydantic import BaseModel, Field, SecretStr

from agent_workflow.channels.events import Attachment, NormalizedChannelEvent
from agent_workflow.channels.onebot.adapter import OneBotAdapter, is_archive_attachment
from agent_workflow.channels.onebot.archive import (
    ArchiveExtractionResult,
    ArchiveInspectionResult,
    ArchiveInspector,
)
from agent_workflow.channels.onebot.artifacts import build_evaluation_request_from_extraction
from agent_workflow.channels.onebot.client import OneBotHttpClient, OneBotSendResult
from agent_workflow.channels.onebot.downloader import DownloadedFile, OneBotFileDownloader
from agent_workflow.channels.onebot.event_handler import OneBotEventHandler
from agent_workflow.channels.onebot.models import OneBotEvent
from agent_workflow.channels.onebot.ws_listener import (
    OneBotWsListener,
    WsConnectionState,
    WsListenerStatus,
)
from agent_workflow.evaluation.models import (
    ArtifactInput,
    ArtifactKind,
    ProjectEvaluationRequest,
    ProjectEvaluationResult,
)
from agent_workflow.evaluation.repository import RepositoryAnalysisError, RepositoryAnalyzer
from agent_workflow.evaluation.repository_agent import (
    AgenticRepositoryReviewer,
    RepositoryProgressCallback,
)
from agent_workflow.evaluation.service import ProjectEvaluationService
from agent_workflow.evaluation.tool_log import get_tool_log_store
from agent_workflow.llm.models import ChatCompletionRequest, ChatMessage
from agent_workflow.llm.openai_compatible import OpenAICompatibleChatClient
from agent_workflow.rag.gateway import RagGateway
from agent_workflow.rag.models import RetrievalQuery

router = APIRouter(prefix="/qq", tags=["qq"])
_adapter = OneBotAdapter()
_inspector = ArchiveInspector()
_evaluator = ProjectEvaluationService()
_repository_analyzer = RepositoryAnalyzer()
_repository_reviewer = AgenticRepositoryReviewer()
_events: list[NormalizedChannelEvent] = []
_tool_logs: list[dict[str, Any]] = []
_ws_listener: OneBotWsListener | None = None
_event_handler: OneBotEventHandler | None = None
_DEFAULT_DOWNLOAD_DIR = Path("data/qq-downloads")
_DEFAULT_EXTRACT_DIR = Path("data/qq-extracted")

# Evaluation request queue — ensures one evaluation at a time
_eval_lock = threading.Lock()
_eval_queue: deque[dict[str, Any]] = deque(maxlen=20)
_eval_active: str | None = None
_eval_thread: threading.Thread | None = None
_URL_RE = re.compile(r"https?://[^\s\]）)>]+", re.IGNORECASE)
_TRIGGER_WORDS = ("课题", "评价", "评测", "分析", "报告", "论文", "项目", "仓库")
def _load_default_prompt() -> str:
    """Load default prompt from file, fallback to built-in."""
    prompt_path = Path("data/evaluation-prompt.txt")
    if prompt_path.exists():
        try:
            return prompt_path.read_text(encoding="utf-8").strip()
        except OSError:
            pass
    return (
        "你是 QQ 课题产物评价智能体。\n\n"
        "你的目标：接收 QQ 中的文字、GitHub 仓库链接、压缩包、报告、论文、"
        "演示文稿、Word 文档、视频转写和代码等课题产物，使用后端提供的"
        "只读工具自主分析，并给出可信、可解释、可落地的评价。\n\n"
        "行为要求：\n"
        "1. 必须基于真实工具结果和已读取内容评价，不要编造未读取的文件或实现细节。\n"
        "2. 进度汇报要简短、自然、基于当前真实工具状态，不要提前给最终结论。\n"
        "3. 最终评价要包含完成度、关键证据、主要不足、代码/工程质量、"
        "可复现性和下一步建议。\n"
        "4. 回复内容适合直接发送到 QQ，语言使用简体中文，避免冗长空话。\n"
    )


DEFAULT_AGENT_SYSTEM_PROMPT = _load_default_prompt()


class QqBlacklistEntry(BaseModel):
    entry_type: Literal["user", "conversation"] = "user"
    value: str = Field(min_length=1)
    reason: str | None = None


class QqAutomationSettings(BaseModel):
    auto_evaluate_enabled: bool = True
    auto_reply_enabled: bool = True
    deep_review_enabled: bool = True
    progress_report_enabled: bool = True
    progress_report_level: Literal["minimal", "normal", "verbose"] = "verbose"
    onebot_api_base_url: str = "http://127.0.0.1:3001"
    access_token: SecretStr | None = Field(default=None, exclude=True)
    topic_title: str = "QQ 上传课题产物"
    topic_goal: str = "综合评价课题所有产物"
    agent_system_prompt: str = DEFAULT_AGENT_SYSTEM_PROMPT
    blacklist: list[QqBlacklistEntry] = Field(default_factory=list)


class QqAutomationSettingsUpdate(BaseModel):
    auto_evaluate_enabled: bool | None = None
    auto_reply_enabled: bool | None = None
    deep_review_enabled: bool | None = None
    progress_report_enabled: bool | None = None
    progress_report_level: Literal["minimal", "normal", "verbose"] | None = None
    onebot_api_base_url: str | None = None
    access_token: str | None = None
    topic_title: str | None = None
    topic_goal: str | None = None
    agent_system_prompt: str | None = None
    blacklist: list[QqBlacklistEntry] | None = None


class QqAutomationSettingsResponse(BaseModel):
    auto_evaluate_enabled: bool
    auto_reply_enabled: bool
    deep_review_enabled: bool
    progress_report_enabled: bool
    progress_report_level: Literal["minimal", "normal", "verbose"]
    onebot_api_base_url: str
    access_token_configured: bool
    topic_title: str
    topic_goal: str
    agent_system_prompt: str
    blacklist: list[QqBlacklistEntry]


class QqToolLogEntry(BaseModel):
    timestamp: str
    conversation_id: str
    tool: str
    target: str | None = None
    status: str
    detail: str | None = None
    arguments: dict[str, Any] = Field(default_factory=dict)


class AutoActionResult(BaseModel):
    action: str
    status: str
    detail: str | None = None
    reply: str | None = None
    llm_review: str | None = None
    evaluation: ProjectEvaluationResult | None = None


class OneBotWebhookResult(BaseModel):
    normalized: NormalizedChannelEvent
    archive_inspections: list[ArchiveInspectionResult] = Field(default_factory=list)
    auto_actions: list[AutoActionResult] = Field(default_factory=list)


class ArchiveInspectRequest(BaseModel):
    path: str


class AttachmentDownloadRequest(BaseModel):
    attachment: Attachment
    download_dir: str | None = None


class ArchiveExtractRequest(BaseModel):
    path: str
    destination_dir: str | None = None


class ArchiveEvaluateRequest(BaseModel):
    path: str
    topic_title: str
    topic_goal: str
    destination_dir: str | None = None


class ArchiveEvaluateResult(BaseModel):
    extraction: ArchiveExtractionResult
    evaluation: ProjectEvaluationResult | None = None


class SendQqMessageRequest(BaseModel):
    conversation_id: str = Field(description="group:123 或 private:456")
    message: str
    onebot_api_base_url: str = "http://127.0.0.1:3001"
    access_token: str | None = None


def _secret_from_env() -> SecretStr | None:
    token = os.getenv("ONEBOT_ACCESS_TOKEN")
    return SecretStr(token) if token else None


def _load_automation_settings() -> QqAutomationSettings:
    """Load automation settings from cache, falling back to env/defaults."""
    from agent_workflow.config_cache import get_settings_cache
    cached = get_settings_cache().get("qq_automation")
    if cached:
        token = cached.pop("access_token", None)
        if token:
            cached["access_token"] = SecretStr(token)
        else:
            cached["access_token"] = _secret_from_env()
        try:
            return QqAutomationSettings.model_validate(cached)
        except Exception:
            pass
    return QqAutomationSettings(access_token=_secret_from_env())


_automation_settings = _load_automation_settings()


def _save_automation_settings() -> None:
    """Persist current automation settings to cache."""
    from agent_workflow.config_cache import get_settings_cache
    data = _automation_settings.model_dump(mode="json", exclude={"access_token"})
    if _automation_settings.access_token:
        data["access_token"] = _automation_settings.access_token.get_secret_value()
    get_settings_cache().set("qq_automation", data)


@router.get("/automation/settings")
def get_qq_automation_settings() -> QqAutomationSettingsResponse:
    return _public_automation_settings()


@router.put("/automation/settings")
def update_qq_automation_settings(
    request: QqAutomationSettingsUpdate,
) -> QqAutomationSettingsResponse:
    global _automation_settings
    updates = request.model_dump(exclude_unset=True, exclude={"access_token"})
    current = _automation_settings.model_dump(exclude={"access_token"})
    current["access_token"] = _automation_settings.access_token
    # Don't overwrite non-empty strings with empty strings
    for key in ("agent_system_prompt", "topic_title", "topic_goal", "onebot_api_base_url"):
        if key in updates and not updates[key] and current.get(key):
            del updates[key]
    current.update(updates)
    if "access_token" in request.model_fields_set:
        current["access_token"] = SecretStr(request.access_token) if request.access_token else None
    _automation_settings = QqAutomationSettings.model_validate(current)
    _save_automation_settings()
    return _public_automation_settings()


@router.post("/onebot/webhook")
def receive_onebot_event(request: Request, event: OneBotEvent) -> dict[str, Any] | OneBotWebhookResult:
    # Silently accept meta events (heartbeat, lifecycle) without processing
    if event.post_type == "meta_event":
        return {"status": "ignored", "reason": "meta_event"}
    normalized = _adapter.normalize(event)
    _events.append(normalized)
    inspections = []
    for attachment in normalized.content.attachments:
        if is_archive_attachment(attachment):
            path = _local_path_from_uri(attachment.uri)
            if path is not None and path.exists():
                inspections.append(_inspector.inspect(path))
    chat_client = getattr(request.app.state, "chat_client", None)
    if not isinstance(chat_client, OpenAICompatibleChatClient):
        chat_client = None
    rag_gateway = getattr(request.app.state, "rag_gateway", None)
    if not hasattr(rag_gateway, "retrieve_fused"):
        rag_gateway = None
    auto_actions = _run_auto_actions(event, normalized, chat_client, rag_gateway)
    return OneBotWebhookResult(
        normalized=normalized,
        archive_inspections=inspections,
        auto_actions=auto_actions,
    )


@router.get("/events")
def list_qq_events(limit: int = 50) -> list[NormalizedChannelEvent]:
    return _events[-max(1, min(limit, 200)) :]


@router.get("/tool-logs")
def list_qq_tool_logs(limit: int = 100) -> list[QqToolLogEntry]:
    logs = _tool_logs[-max(1, min(limit, 500)) :]
    return [QqToolLogEntry.model_validate(item) for item in logs]


@router.get("/queue")
def get_eval_queue_status() -> dict[str, Any]:
    """Get the current evaluation queue status."""
    pending = []
    for item in _eval_queue:
        n = item.get("normalized")
        pending.append(n.conversation_id if n else "unknown")
    return {
        "active": _eval_active,
        "queue_length": len(_eval_queue),
        "pending_conversations": pending,
        "busy": _eval_lock.locked(),
        "worker_alive": _eval_thread.is_alive() if _eval_thread else False,
    }


@router.post("/files/download")
def download_attachment(request: AttachmentDownloadRequest) -> DownloadedFile:
    downloader = OneBotFileDownloader(Path(request.download_dir or _DEFAULT_DOWNLOAD_DIR))
    return downloader.download_attachment(request.attachment)


@router.post("/archive/inspect")
def inspect_archive(request: ArchiveInspectRequest) -> ArchiveInspectionResult:
    return _inspector.inspect(Path(request.path))


@router.post("/archive/extract")
def extract_archive(request: ArchiveExtractRequest) -> ArchiveExtractionResult:
    destination = Path(request.destination_dir or _DEFAULT_EXTRACT_DIR)
    return _inspector.extract_safe(Path(request.path), destination)


@router.post("/archive/evaluate")
def evaluate_archive(request: ArchiveEvaluateRequest) -> ArchiveEvaluateResult:
    destination = Path(request.destination_dir or _DEFAULT_EXTRACT_DIR)
    extraction = _inspector.extract_safe(Path(request.path), destination)
    if not extraction.inspection.safe:
        return ArchiveEvaluateResult(extraction=extraction, evaluation=None)
    evaluation_request = build_evaluation_request_from_extraction(
        extraction,
        topic_title=request.topic_title,
        topic_goal=request.topic_goal,
    )
    return ArchiveEvaluateResult(
        extraction=extraction,
        evaluation=_evaluator.evaluate(evaluation_request),
    )


@router.post("/send")
def send_qq_message(request: SendQqMessageRequest) -> OneBotSendResult:
    client = OneBotHttpClient(
        base_url=request.onebot_api_base_url,
        access_token=SecretStr(request.access_token) if request.access_token else None,
    )
    if request.conversation_id.startswith("group:"):
        group_id = request.conversation_id.removeprefix("group:")
        return client.send_group_msg(group_id, request.message)
    if request.conversation_id.startswith("private:"):
        user_id = request.conversation_id.removeprefix("private:")
        return client.send_private_msg(user_id, request.message)
    raise ValueError("conversation_id must start with group: or private:")


# ------------------------------------------------------------------
# WebSocket management endpoints
# ------------------------------------------------------------------


class WsConnectRequest(BaseModel):
    url: str = Field(description="OneBot forward WebSocket URL, e.g. ws://127.0.0.1:3001/ws")
    access_token: str | None = None
    reconnect_max_seconds: int = 60


class WsConnectResponse(BaseModel):
    status: str
    detail: str | None = None
    listener_status: WsListenerStatus | None = None


@router.post("/ws/connect")
async def ws_connect(request: WsConnectRequest) -> WsConnectResponse:
    """Start a background WebSocket connection to the OneBot server."""
    global _ws_listener, _event_handler

    if _ws_listener is not None and _ws_listener.state in {
        WsConnectionState.CONNECTED,
        WsConnectionState.CONNECTING,
        WsConnectionState.RECONNECTING,
    }:
        return WsConnectResponse(
            status="already_connected",
            detail="WebSocket listener is already active",
            listener_status=_ws_listener.status(),
        )

    _ws_listener = OneBotWsListener(
        url=request.url,
        access_token=request.access_token,
        reconnect_max_seconds=request.reconnect_max_seconds,
    )

    _event_handler = OneBotEventHandler()
    await _event_handler.start()

    async def _ws_event_callback(event: OneBotEvent) -> None:
        await _event_handler.handle_event(event)

    try:
        await _ws_listener.listen(_ws_event_callback)
    except Exception as exc:  # noqa: BLE001
        return WsConnectResponse(
            status="failed",
            detail=f"Connection failed: {exc}",
        )

    return WsConnectResponse(
        status="connected",
        detail=f"Connected to {request.url}",
        listener_status=_ws_listener.status(),
    )


@router.post("/ws/disconnect")
async def ws_disconnect() -> WsConnectResponse:
    """Disconnect the active WebSocket connection."""
    global _ws_listener, _event_handler

    if _ws_listener is None or _ws_listener.state == WsConnectionState.DISCONNECTED:
        return WsConnectResponse(
            status="not_connected",
            detail="No active WebSocket connection",
        )

    await _ws_listener.disconnect()
    if _event_handler is not None:
        await _event_handler.stop()
        _event_handler = None

    status = _ws_listener.status()
    _ws_listener = None
    return WsConnectResponse(
        status="disconnected",
        detail="WebSocket connection closed",
        listener_status=status,
    )


@router.get("/ws/status")
def ws_status() -> WsListenerStatus:
    """Return the current WebSocket connection status."""
    if _ws_listener is None:
        return WsListenerStatus(
            state=WsConnectionState.DISCONNECTED,
            url="",
            reconnect_attempts=0,
            last_event_time=None,
            total_events_received=0,
        )
    return _ws_listener.status()


def _public_automation_settings() -> QqAutomationSettingsResponse:
    return QqAutomationSettingsResponse(
        auto_evaluate_enabled=_automation_settings.auto_evaluate_enabled,
        auto_reply_enabled=_automation_settings.auto_reply_enabled,
        deep_review_enabled=_automation_settings.deep_review_enabled,
        progress_report_enabled=_automation_settings.progress_report_enabled,
        progress_report_level=_automation_settings.progress_report_level,
        onebot_api_base_url=_automation_settings.onebot_api_base_url,
        access_token_configured=_automation_settings.access_token is not None,
        topic_title=_automation_settings.topic_title,
        topic_goal=_automation_settings.topic_goal,
        agent_system_prompt=_automation_settings.agent_system_prompt,
        blacklist=_automation_settings.blacklist,
    )


def _run_auto_actions(
    event: OneBotEvent,
    normalized: NormalizedChannelEvent,
    chat_client: OpenAICompatibleChatClient | None,
    rag_gateway: RagGateway | None,
) -> list[AutoActionResult]:
    global _eval_active
    settings = _automation_settings
    if not settings.auto_evaluate_enabled and not settings.auto_reply_enabled:
        return []
    if event.post_type == "message_sent":
        return []
    # Ignore messages from the bot itself (prevents self-triggering loops)
    if event.self_id and event.user_id and str(event.self_id) == str(event.user_id):
        return []
    if _is_blacklisted(normalized, settings):
        return [AutoActionResult(action="blacklist", status="skipped", detail="命中黑名单")]
    if normalized.conversation_id.startswith("group:") and not _group_message_should_trigger(
        event,
        normalized,
    ):
        return []

    actions: list[AutoActionResult] = []
    reply_text: str | None = None
    archive_paths, archive_actions = _archive_paths_from_event(normalized)
    actions.extend(archive_actions)

    # Queue control: heavy evaluation tasks are serialized
    needs_evaluation = (
        (settings.auto_evaluate_enabled and archive_paths)
        or (settings.auto_evaluate_enabled and _text_should_evaluate(normalized.content.text))
    )
    if needs_evaluation:
        if not _eval_lock.acquire(blocking=False):
            # Another evaluation is running — queue this one for background processing
            queue_msg = (
                f"当前有评测任务正在进行中，你的请求已排队"
                f"（第 {len(_eval_queue) + 1} 位）。完成后会自动处理。"
            )
            if settings.auto_reply_enabled:
                _send_auto_reply(normalized, queue_msg, settings)
            _eval_queue.append({
                "event": event,
                "normalized": normalized,
                "chat_client": chat_client,
                "rag_gateway": rag_gateway,
            })
            return [AutoActionResult(
                action="queued", status="waiting", detail=queue_msg
            )]
        _eval_active = normalized.message_id

    try:
        if settings.auto_evaluate_enabled and archive_paths:
            result = _evaluate_archive_for_auto_reply(
                archive_paths[0],
                settings,
                chat_client,
                normalized,
            )
            actions.append(result)
            if result.llm_review:
                reply_text = result.llm_review
            elif result.evaluation is not None:
                reply_text = _format_evaluation_reply(result.evaluation)
        elif settings.auto_evaluate_enabled and _text_should_evaluate(
            normalized.content.text
        ):
            result = _evaluate_text_for_auto_reply(
                normalized, settings, chat_client, rag_gateway
            )
            actions.append(result)
            if result.llm_review:
                reply_text = result.llm_review
            elif result.evaluation is not None:
                reply_text = _format_evaluation_reply(result.evaluation)
        elif settings.auto_reply_enabled and _should_send_help(normalized):
            # Admin or private chat without URL/archive: call LLM for a real response
            if chat_client is not None and chat_client.api_key_configured:
                reply_text = _llm_chat_reply(normalized, settings, chat_client)
                actions.append(
                    AutoActionResult(action="llm_chat", status="success", reply=reply_text)
                )
            else:
                reply_text = (
                    "已收到。请发送课题说明、GitHub 仓库链接，或上传 zip/tar.gz 压缩包，"
                    "我会自动评价并回复摘要。"
                )
                actions.append(
                    AutoActionResult(
                        action="help_reply", status="prepared", reply=reply_text
                    )
                )
    finally:
        if needs_evaluation:
            _eval_active = None
            _eval_lock.release()
            # Process next queued item in background
            _process_next_in_queue()

    if settings.auto_reply_enabled and reply_text:
        # Generate and send PDF report for evaluation results
        if needs_evaluation and reply_text and len(reply_text) > 200:
            pdf_result = _send_pdf_report(normalized, reply_text, settings)
            if pdf_result:
                actions.append(pdf_result)
        else:
            actions.append(_send_auto_reply(normalized, reply_text, settings))
    return actions


def _process_next_in_queue() -> None:
    """Process the next queued evaluation request in a background thread."""
    global _eval_thread
    if not _eval_queue:
        return
    if _eval_thread is not None and _eval_thread.is_alive():
        return  # Already processing

    def _worker() -> None:
        while _eval_queue:
            item = _eval_queue.popleft()
            try:
                _run_auto_actions(
                    event=item["event"],
                    normalized=item["normalized"],
                    chat_client=item["chat_client"],
                    rag_gateway=item["rag_gateway"],
                )
            except Exception:  # noqa: BLE001
                pass

    _eval_thread = threading.Thread(target=_worker, daemon=True)
    _eval_thread.start()


def _archive_paths_from_event(
    normalized: NormalizedChannelEvent,
) -> tuple[list[Path], list[AutoActionResult]]:
    paths: list[Path] = []
    actions: list[AutoActionResult] = []
    downloader = OneBotFileDownloader(_DEFAULT_DOWNLOAD_DIR)
    for attachment in normalized.content.attachments:
        if not is_archive_attachment(attachment):
            continue
        local_path = _local_path_from_uri(attachment.uri)
        if local_path is not None and local_path.exists():
            paths.append(local_path)
            continue
        try:
            downloaded = downloader.download_attachment(attachment)
            downloaded_path = Path(downloaded.path)
            paths.append(downloaded_path)
            actions.append(
                AutoActionResult(
                    action="download_archive",
                    status="success",
                    detail=str(downloaded.path),
                )
            )
        except Exception as exc:  # noqa: BLE001 - keep webhook resilient
            actions.append(
                AutoActionResult(action="download_archive", status="failed", detail=str(exc))
            )
    return paths, actions


def _evaluate_archive_for_auto_reply(
    path: Path,
    settings: QqAutomationSettings,
    chat_client: OpenAICompatibleChatClient | None,
    normalized: NormalizedChannelEvent,
) -> AutoActionResult:
    try:
        extraction = _inspector.extract_safe(path, _DEFAULT_EXTRACT_DIR)
        _send_archive_progress(normalized, path, extraction, settings, chat_client)
        if not extraction.inspection.safe:
            return AutoActionResult(
                action="evaluate_archive",
                status="skipped",
                detail="压缩包安全检查未通过，已跳过自动评价。",
            )
        evaluation_request = build_evaluation_request_from_extraction(
            extraction,
            topic_title=settings.topic_title,
            topic_goal=settings.topic_goal,
        )
        evaluation = _evaluator.evaluate(evaluation_request)
        llm_review = _build_llm_review(evaluation_request, evaluation, settings, chat_client)
        return AutoActionResult(
            action="evaluate_archive",
            status="success",
            detail=str(path),
            llm_review=llm_review,
            evaluation=evaluation,
        )
    except Exception as exc:  # noqa: BLE001 - keep webhook resilient
        return AutoActionResult(action="evaluate_archive", status="failed", detail=str(exc))


def _evaluate_text_for_auto_reply(
    normalized: NormalizedChannelEvent,
    settings: QqAutomationSettings,
    chat_client: OpenAICompatibleChatClient | None,
    rag_gateway: RagGateway | None,
) -> AutoActionResult:
    text = normalized.content.text or ""
    url = _first_url(text)
    detail = None
    try:
        if settings.deep_review_enabled and url and "github.com" in url.lower():
            seed_request = _build_text_evaluation_request(normalized, settings)
            seed_evaluation = _evaluator.evaluate(seed_request)
            review = _repository_reviewer.review_url(
                url,
                topic_title=settings.topic_title,
                topic_goal=settings.topic_goal,
                chat_client=chat_client,
                rule_evaluation=seed_evaluation,
                progress_callback=_build_progress_callback(normalized, settings),
                tool_log_callback=_build_tool_log_callback(normalized),
                rag_callback=_build_rag_callback(rag_gateway),
                agent_system_prompt=settings.agent_system_prompt,
                progress_level=settings.progress_report_level,
            )
            evaluation_request = ProjectEvaluationRequest(
                topic_title=settings.topic_title,
                topic_goal=settings.topic_goal,
                artifacts=[review.to_artifact()],
            )
            evaluation = _evaluator.evaluate(evaluation_request)
            detail = "AI 已在临时工作区自主克隆仓库、列出文件、读取文件并完成代码审查。"
            return AutoActionResult(
                action="agentic_repository_review",
                status="success",
                detail=detail,
                llm_review=review.final_review,
                evaluation=evaluation,
            )
        evaluation_request = _build_text_evaluation_request(normalized, settings)
        evaluation = _evaluator.evaluate(evaluation_request)
        llm_review = _build_llm_review(evaluation_request, evaluation, settings, chat_client)
        return AutoActionResult(
            action="evaluate_text",
            status="success",
            detail=detail,
            llm_review=llm_review,
            evaluation=evaluation,
        )
    except RepositoryAnalysisError as exc:
        evaluation_request = _build_text_evaluation_request(normalized, settings)
        evaluation = _evaluator.evaluate(evaluation_request)
        return AutoActionResult(
            action="evaluate_text",
            status="partial",
            detail=f"仓库深度分析失败，已回退文本评价：{exc}",
            evaluation=evaluation,
        )
    except Exception as exc:  # noqa: BLE001 - keep webhook resilient
        return AutoActionResult(action="evaluate_text", status="failed", detail=str(exc))


def _archive_progress_state_message(
    path: Path,
    extraction: ArchiveExtractionResult,
    files: list[str],
) -> str:
    return (
        "当前工具状态：QQ 上传的压缩包已安全检查并解压。\n"
        "请根据你的主提示词生成一条简短 QQ 进度汇报，不要提前给最终结论。\n\n"
        f"压缩包：{path.name}\n"
        f"安全检查：{extraction.inspection.safe}\n"
        f"检测类型：{extraction.inspection.detected_artifacts}\n"
        f"文件列表：{files}\n"
    )


def _send_archive_progress(
    normalized: NormalizedChannelEvent,
    path: Path,
    extraction: ArchiveExtractionResult,
    settings: QqAutomationSettings,
    chat_client: OpenAICompatibleChatClient | None,
) -> None:
    if (
        not settings.progress_report_enabled
        or chat_client is None
        or not chat_client.api_key_configured
    ):
        return
    try:
        files = [Path(item).name for item in extraction.extracted_files[:30]]
        prompt = _archive_progress_state_message(path, extraction, files)
        result = chat_client.chat(
            ChatCompletionRequest(
                messages=[
                    ChatMessage(role="system", content=settings.agent_system_prompt),
                    ChatMessage(role="user", content=prompt),
                ],
                temperature=0.5,
                max_tokens=120,
            )
        )
        message = result.content.strip()[:220]
        if message:
            _send_auto_reply(normalized, message, settings)
    except Exception:
        return


def _build_tool_log_callback(normalized: NormalizedChannelEvent):
    def callback(tool: str, arguments: dict[str, Any], result: dict[str, Any]) -> None:
        target = _tool_target(arguments)
        entry = QqToolLogEntry(
            timestamp=datetime.now(UTC).isoformat(timespec="seconds"),
            conversation_id=normalized.conversation_id,
            tool=tool,
            target=target,
            status="success" if result.get("ok") else "failed",
            detail=str(
                result.get("error") or result.get("message")
                or result.get("reason") or ""
            )[:500],
            arguments=arguments,
        )
        _tool_logs.append(entry.model_dump())
        del _tool_logs[:-500]
        # Also log to the shared global tool log store
        get_tool_log_store().log(
            session_id=f"qq:{normalized.conversation_id}",
            tool=tool,
            arguments=arguments,
            result=result,
        )

    return callback


def _tool_target(arguments: dict[str, Any]) -> str | None:
    for key in ("url", "path", "query", "topic_name"):
        value = arguments.get(key)
        if value:
            return str(value)
    message = arguments.get("message")
    return str(message)[:60] if message else None


def _build_rag_callback(rag_gateway: RagGateway | None):
    if rag_gateway is None:
        return None

    def callback(query: str) -> list[dict[str, Any]]:
        result = rag_gateway.retrieve_fused(
            RetrievalQuery(query=query, text_top_k=8, visual_top_k=4)
        )
        return [item.model_dump() for item in result.evidence[:8]]

    return callback


def _build_progress_callback(
    normalized: NormalizedChannelEvent,
    settings: QqAutomationSettings,
) -> RepositoryProgressCallback | None:
    if not settings.progress_report_enabled or not settings.auto_reply_enabled:
        return None
    max_reports = {"minimal": 1, "normal": 3, "verbose": 10}[settings.progress_report_level]
    sent_count = 0

    def callback(message: str) -> None:
        nonlocal sent_count
        if sent_count >= max_reports:
            return
        sent_count += 1
        _send_auto_reply(normalized, message, settings)

    return callback


def _send_auto_reply(
    normalized: NormalizedChannelEvent,
    message: str,
    settings: QqAutomationSettings,
) -> AutoActionResult:
    try:
        client = OneBotHttpClient(
            base_url=settings.onebot_api_base_url,
            access_token=settings.access_token,
        )
        conv = normalized.conversation_id
        # Group chats: always quote the original message
        if conv.startswith("group:"):
            group_id = conv.removeprefix("group:")
            result = client.send_group_msg(
                group_id, message, reply_to=normalized.message_id
            )
        elif conv.startswith("private:"):
            user_id = conv.removeprefix("private:")
            result = client.send_private_msg(user_id, message)
        else:
            raise ValueError(f"unknown conversation: {conv}")
        return AutoActionResult(
            action="send_reply",
            status="success",
            detail=str(result.response.get("data") or result.response),
            reply=message,
        )
    except Exception as exc:  # noqa: BLE001 - keep webhook resilient
        return AutoActionResult(
            action="send_reply",
            status="failed",
            detail=str(exc),
            reply=message,
        )


def _send_pdf_report(
    normalized: NormalizedChannelEvent,
    review_text: str,
    settings: QqAutomationSettings,
) -> AutoActionResult | None:
    """Generate PDF from evaluation text and send as file to QQ."""
    try:
        from agent_workflow.evaluation.pdf_report import generate_evaluation_pdf
        import time as _time

        # Generate PDF
        timestamp = datetime.now(UTC).strftime("%Y%m%d_%H%M%S")
        filename = f"课题评测报告_{timestamp}.pdf"
        pdf_path = generate_evaluation_pdf(review_text, filename)
        pdf_data = pdf_path.read_bytes()

        # Send PDF file via base64 (works with Docker NapCat)
        client = OneBotHttpClient(
            base_url=settings.onebot_api_base_url,
            access_token=settings.access_token,
        )
        conv = normalized.conversation_id

        # Try sending PDF with one retry
        last_error = None
        for attempt in range(2):
            try:
                if conv.startswith("group:"):
                    group_id = conv.removeprefix("group:")
                    client.send_group_file_base64(group_id, pdf_data, filename)
                elif conv.startswith("private:"):
                    user_id = conv.removeprefix("private:")
                    client.send_private_file_base64(user_id, pdf_data, filename)
                return AutoActionResult(
                    action="send_pdf",
                    status="success",
                    detail=f"PDF 已发送：{filename} ({len(pdf_data)} bytes)",
                )
            except Exception as exc:  # noqa: BLE001
                last_error = exc
                if attempt == 0:
                    _time.sleep(2)  # Wait before retry

        # Both attempts failed
        _send_auto_reply(
            normalized,
            f"评测已完成，但 PDF 报告发送失败（{last_error}）。请联系管理员获取报告。",
            settings,
        )
        return AutoActionResult(
            action="send_pdf",
            status="failed",
            detail=f"PDF 发送失败（重试后）：{last_error}",
        )
    except Exception as exc:  # noqa: BLE001
        _send_auto_reply(
            normalized,
            f"评测已完成，但报告生成失败（{exc}）。请联系管理员。",
            settings,
        )
        return AutoActionResult(
            action="send_pdf",
            status="failed",
            detail=f"PDF 生成失败：{exc}",
        )


def _llm_chat_reply(
    normalized: NormalizedChannelEvent,
    settings: QqAutomationSettings,
    chat_client: OpenAICompatibleChatClient,
) -> str:
    """Call LLM to generate a conversational reply based on the system prompt."""
    text = normalized.content.text or ""
    # Strip the @mention prefix for cleaner input
    import re as _re
    text = _re.sub(r"@\d+\s*", "", text).strip() or text
    try:
        result = chat_client.chat(
            ChatCompletionRequest(
                messages=[
                    ChatMessage(role="system", content=settings.agent_system_prompt),
                    ChatMessage(role="user", content=text),
                ],
                temperature=0.3,
                max_tokens=800,
            ),
            session_id=f"qq:{normalized.conversation_id}",
        )
        return result.content.strip()[:2000]
    except Exception as exc:  # noqa: BLE001
        return f"模型调用失败：{exc}"


def _build_text_evaluation_request(
    normalized: NormalizedChannelEvent,
    settings: QqAutomationSettings,
) -> ProjectEvaluationRequest:
    text = normalized.content.text or ""
    url = _first_url(text)
    is_repository = bool(url and "github.com" in url.lower())
    repository_summary = None
    if is_repository:
        repository_summary = f"QQ 消息中提交的代码仓库链接：{url}\n{text}"
    artifact = ArtifactInput(
        artifact_id=f"qq-{normalized.message_id}",
        kind=ArtifactKind.CODE_REPOSITORY if is_repository else ArtifactKind.OTHER,
        title="QQ 消息提交产物",
        uri=url,
        text=None if is_repository else text,
        repository_summary=repository_summary,
        metadata={
            "conversation_id": normalized.conversation_id,
            "sender": normalized.sender.user_id,
        },
    )
    return ProjectEvaluationRequest(
        topic_title=settings.topic_title,
        topic_goal=settings.topic_goal,
        artifacts=[artifact],
    )


def _build_llm_review(
    evaluation_request: ProjectEvaluationRequest,
    evaluation: ProjectEvaluationResult,
    settings: QqAutomationSettings,
    chat_client: OpenAICompatibleChatClient | None,
) -> str | None:
    if (
        not settings.deep_review_enabled
        or chat_client is None
        or not chat_client.api_key_configured
    ):
        return None
    try:
        result = chat_client.chat(
            ChatCompletionRequest(
                messages=[
                    ChatMessage(role="system", content=settings.agent_system_prompt),
                    ChatMessage(
                        role="user",
                        content=_llm_review_prompt(evaluation_request, evaluation),
                    ),
                ],
                temperature=0.2,
                max_tokens=1200,
            )
        )
        return result.content.strip()[:4000]
    except Exception:  # noqa: BLE001 - auto reply must fall back safely
        return None


def _llm_review_prompt(
    evaluation_request: ProjectEvaluationRequest,
    evaluation: ProjectEvaluationResult,
) -> str:
    artifacts_text = "\n\n".join(
        _artifact_text_for_prompt(artifact) for artifact in evaluation_request.artifacts
    )[:80_000]
    return _artifact_review_state_message(evaluation_request, evaluation, artifacts_text)


def _artifact_review_state_message(
    evaluation_request: ProjectEvaluationRequest,
    evaluation: ProjectEvaluationResult,
    artifacts_text: str,
) -> str:
    return (
        "当前工具状态：产物证据已整理，规则评分已完成。\n"
        "请根据你的主提示词生成最终评价。\n\n"
        f"课题：{evaluation_request.topic_title}\n"
        f"目标：{evaluation_request.topic_goal}\n"
        f"规则评分：{evaluation.overall_score}/100\n"
        f"规则摘要：{evaluation.summary}\n"
        f"规则建议：{'; '.join(evaluation.recommendations[:6])}\n\n"
        f"产物证据：\n{artifacts_text}"
    )


def _artifact_text_for_prompt(artifact: ArtifactInput) -> str:
    parts = [
        f"标题：{artifact.title}",
        f"类型：{artifact.kind}",
        f"资源地址：{artifact.uri or '-'}",
        artifact.text or "",
        artifact.transcript or "",
        artifact.repository_summary or "",
        str(artifact.metadata),
    ]
    return "\n".join(part for part in parts if part)[:30_000]


def _format_evaluation_reply(evaluation: ProjectEvaluationResult) -> str:
    suggestions = evaluation.recommendations or evaluation.next_steps
    suggestion_text = "\n".join(f"- {item}" for item in suggestions[:3]) or "- 暂无"
    return (
        f"课题评价完成：{evaluation.summary}\n"
        f"总分：{evaluation.overall_score}/100\n"
        f"主要建议：\n{suggestion_text}"
    )


def _is_blacklisted(
    normalized: NormalizedChannelEvent,
    settings: QqAutomationSettings,
) -> bool:
    for entry in settings.blacklist:
        value = entry.value.strip()
        if entry.entry_type == "user" and value == normalized.sender.user_id:
            return True
        if entry.entry_type == "conversation" and value in {
            normalized.conversation_id,
            normalized.conversation_id.removeprefix("group:"),
            normalized.conversation_id.removeprefix("private:"),
        }:
            return True
    return False


def _group_message_should_trigger(
    event: OneBotEvent,
    normalized: NormalizedChannelEvent,
) -> bool:
    text = normalized.content.text or ""
    # Admin user @-ing the bot always triggers
    if normalized.sender.user_id == "2813994715":
        if str(event.self_id or "") and str(event.self_id) in text:
            return True
    # Anyone with archive attachment triggers
    if any(is_archive_attachment(attachment) for attachment in normalized.content.attachments):
        return True
    # Anyone with URL or trigger keywords triggers
    if any(word in text for word in _TRIGGER_WORDS) or bool(_first_url(text)):
        return True
    # Other users @-ing the bot only trigger if they have URL or keywords
    if str(event.self_id or "") and str(event.self_id) in text:
        return bool(_first_url(text)) or any(
            word in text for word in _TRIGGER_WORDS
        ) or any(is_archive_attachment(a) for a in normalized.content.attachments)
    return False


def _text_should_evaluate(text: str | None) -> bool:
    if not text:
        return False
    cleaned = text.strip()
    return bool(_first_url(cleaned)) or len(cleaned) >= 20 or any(
        word in cleaned for word in _TRIGGER_WORDS
    )


def _should_send_help(normalized: NormalizedChannelEvent) -> bool:
    # Admin user always gets a reply (private or group @)
    if normalized.sender.user_id == "2813994715":
        return True
    return normalized.conversation_id.startswith("private:")


def _first_url(text: str) -> str | None:
    match = _URL_RE.search(text)
    return match.group(0) if match else None


def _local_path_from_uri(uri: str) -> Path | None:
    if uri.startswith("file://"):
        return Path(uri.removeprefix("file://"))
    if uri.startswith("http://") or uri.startswith("https://"):
        return None
    return Path(uri)
