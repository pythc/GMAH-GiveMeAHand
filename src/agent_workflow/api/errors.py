"""HTTP exception handlers for predictable API errors."""

from typing import Any

import httpx
from fastapi import Request, status
from fastapi.responses import JSONResponse

from agent_workflow.channels.onebot.adapter import OneBotAdapterError
from agent_workflow.channels.onebot.client import OneBotClientError
from agent_workflow.channels.onebot.downloader import FileDownloadError
from agent_workflow.llm.openai_compatible import ChatModelError
from agent_workflow.mcp.http_gateway import McpGatewayError
from agent_workflow.orchestrator.service import SessionOrchestratorError
from agent_workflow.rag.qdrant_gateway import QdrantGatewayError
from agent_workflow.security.approval import ApprovalError
from agent_workflow.tools.executor import ToolExecutionError
from agent_workflow.tools.registry import ToolRegistryError


def install_exception_handlers(app: Any) -> None:
    """Install exception handlers that avoid leaking 500s for known failures."""

    app.add_exception_handler(ChatModelError, _chat_model_error)
    app.add_exception_handler(httpx.HTTPStatusError, _http_status_error)
    app.add_exception_handler(httpx.RequestError, _http_request_error)
    app.add_exception_handler(McpGatewayError, _mcp_gateway_error)
    app.add_exception_handler(QdrantGatewayError, _qdrant_gateway_error)
    app.add_exception_handler(ApprovalError, _bad_request_error)
    app.add_exception_handler(ToolExecutionError, _bad_request_error)
    app.add_exception_handler(ToolRegistryError, _bad_request_error)
    app.add_exception_handler(SessionOrchestratorError, _bad_request_error)
    app.add_exception_handler(OneBotAdapterError, _bad_request_error)
    app.add_exception_handler(FileDownloadError, _bad_request_error)
    app.add_exception_handler(OneBotClientError, _bad_request_error)
    app.add_exception_handler(ValueError, _bad_request_error)


async def _chat_model_error(request: Request, exc: ChatModelError) -> JSONResponse:
    return _json_error(
        status.HTTP_503_SERVICE_UNAVAILABLE,
        "chat_model_error",
        str(exc),
    )


async def _http_status_error(request: Request, exc: httpx.HTTPStatusError) -> JSONResponse:
    return _json_error(
        status.HTTP_502_BAD_GATEWAY,
        "upstream_http_error",
        _upstream_detail(exc.response),
        {"upstream_status": exc.response.status_code},
    )


async def _http_request_error(request: Request, exc: httpx.RequestError) -> JSONResponse:
    return _json_error(
        status.HTTP_502_BAD_GATEWAY,
        "upstream_request_error",
        str(exc),
    )


async def _mcp_gateway_error(request: Request, exc: McpGatewayError) -> JSONResponse:
    message = str(exc)
    status_code = status.HTTP_400_BAD_REQUEST
    if "MCP error from" in message:
        status_code = status.HTTP_502_BAD_GATEWAY
    return _json_error(status_code, "mcp_gateway_error", message)


async def _qdrant_gateway_error(request: Request, exc: QdrantGatewayError) -> JSONResponse:
    return _json_error(status.HTTP_502_BAD_GATEWAY, "qdrant_gateway_error", str(exc))


async def _bad_request_error(request: Request, exc: Exception) -> JSONResponse:
    return _json_error(status.HTTP_400_BAD_REQUEST, exc.__class__.__name__, str(exc))


def _upstream_detail(response: httpx.Response) -> str:
    try:
        payload = response.json()
    except ValueError:
        return response.text or response.reason_phrase

    if isinstance(payload, dict):
        error = payload.get("error")
        if isinstance(error, dict):
            message = error.get("message")
            if isinstance(message, str):
                return message
        detail = payload.get("detail")
        if isinstance(detail, str):
            return detail
    return response.reason_phrase


def _json_error(
    status_code: int,
    error: str,
    detail: str,
    extra: dict[str, Any] | None = None,
) -> JSONResponse:
    payload: dict[str, Any] = {"error": error, "detail": detail}
    if extra:
        payload.update(extra)
    return JSONResponse(status_code=status_code, content=payload)
