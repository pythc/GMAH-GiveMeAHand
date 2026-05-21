"""FastAPI application factory."""

from __future__ import annotations

from typing import Any

from fastapi import Depends, FastAPI, Request, Response
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint

from agent_workflow import __version__
from agent_workflow.api.dependencies import (
    build_default_chat_client,
    build_default_langgraph_runtime,
    build_default_mcp_gateway,
    build_default_orchestrator,
    build_default_rag_gateway,
)
from agent_workflow.api.errors import install_exception_handlers
from agent_workflow.api.routes.agent import router as agent_router
from agent_workflow.api.routes.approvals import router as approvals_router
from agent_workflow.api.routes.auth import router as auth_router
from agent_workflow.api.routes.evaluation import router as evaluation_router
from agent_workflow.api.routes.mcp import router as mcp_router
from agent_workflow.api.routes.model import router as model_router
from agent_workflow.api.routes.qq import router as qq_router
from agent_workflow.api.routes.rag import router as rag_router
from agent_workflow.api.routes.sessions import router as sessions_router
from agent_workflow.config import AppSettings, get_settings
from agent_workflow.security.auth import AUTH_PUBLIC_PATHS, AuthSettings, get_current_user


class _AuthMiddleware(BaseHTTPMiddleware):
    """Middleware that enforces authentication on non-public endpoints."""

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        # Always allow public paths through without auth checks
        if request.url.path in AUTH_PUBLIC_PATHS:
            return await call_next(request)
        # Let the route-level dependency handle actual token validation
        return await call_next(request)


def _build_auth_settings(settings: AppSettings) -> AuthSettings:
    """Build AuthSettings from the application configuration."""
    api_keys_list = [k.strip() for k in settings.api_keys.split(",") if k.strip()]
    return AuthSettings(
        jwt_secret_key=settings.jwt_secret_key.get_secret_value(),
        enabled=settings.auth_enabled,
        api_keys=api_keys_list,
        admin_username=settings.admin_username,
        admin_password=settings.admin_password.get_secret_value(),
    )


def create_app(settings: AppSettings | None = None) -> FastAPI:
    """Create the HTTP API application.

    Args:
        settings: Optional AppSettings override (useful for testing).
    """
    if settings is None:
        settings = get_settings()

    auth_settings = _build_auth_settings(settings)

    app = FastAPI(
        title="Agent Workflow",
        version=__version__,
        description=("Layered agent platform scaffold for MCP, tools, skills, RAG, and memory."),
    )
    install_exception_handlers(app)

    # Store auth settings on app state for dependency injection
    app.state.auth_settings = auth_settings

    # Register auth middleware when authentication is enabled
    if auth_settings.enabled:
        app.add_middleware(_AuthMiddleware)

    app.state.orchestrator = build_default_orchestrator()
    app.state.langgraph_runtime = build_default_langgraph_runtime(app.state.orchestrator)
    app.state.rag_gateway = build_default_rag_gateway()
    app.state.mcp_gateway = build_default_mcp_gateway()
    app.state.chat_client = build_default_chat_client()

    # Auth routes (login is always accessible)
    app.include_router(auth_router)

    # Protected routes — when auth is enabled, these require get_current_user
    if auth_settings.enabled:
        protected_deps: list[Any] = [Depends(get_current_user)]
        agent_router.dependencies = protected_deps
        sessions_router.dependencies = protected_deps
        approvals_router.dependencies = protected_deps
        rag_router.dependencies = protected_deps
        mcp_router.dependencies = protected_deps
        model_router.dependencies = protected_deps
        evaluation_router.dependencies = protected_deps
        qq_router.dependencies = protected_deps

    app.include_router(agent_router)
    app.include_router(sessions_router)
    app.include_router(approvals_router)
    app.include_router(rag_router)
    app.include_router(mcp_router)
    app.include_router(model_router)
    app.include_router(evaluation_router)
    app.include_router(qq_router)

    @app.get("/healthz", tags=["system"])
    def healthz() -> dict[str, str]:
        return {"status": "ok", "version": __version__}

    @app.get("/logs", tags=["system"])
    def get_activity_logs(
        limit: int = 200,
        session_id: str | None = None,
        kind: str | None = None,
    ) -> list[dict[str, Any]]:
        """Global activity logs — all model calls, tool invocations, progress, errors."""
        from agent_workflow.evaluation.tool_log import LogKind, get_tool_log_store

        store = get_tool_log_store()
        log_kind = LogKind(kind) if kind else None
        entries = store.list(limit=limit, session_id=session_id, kind=log_kind)
        return [e.model_dump() for e in entries]

    return app
