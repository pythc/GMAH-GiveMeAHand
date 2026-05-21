"""FastAPI dependency helpers."""

from pathlib import Path
from typing import cast

from fastapi import Request

from agent_workflow.config import AppSettings, get_settings
from agent_workflow.integrations.grading.adapter import LocalGradingSystemAdapter
from agent_workflow.integrations.grading.tools import build_grading_executors
from agent_workflow.llm.openai_compatible import OpenAICompatibleChatClient
from agent_workflow.mcp.config import load_mcp_gateway_config
from agent_workflow.mcp.http_gateway import StreamableHttpMcpGateway
from agent_workflow.orchestrator.checkpoint import InMemoryCheckpointStore, RedisCheckpointStore
from agent_workflow.orchestrator.langgraph_runtime import LangGraphSessionRuntime
from agent_workflow.orchestrator.service import SessionOrchestrator
from agent_workflow.rag.config import load_rag_config
from agent_workflow.rag.embeddings import (
    CrossEncoderReranker,
    HashEmbeddingModel,
    OpenAICompatibleEmbeddingModel,
)
from agent_workflow.rag.gateway import RagGateway
from agent_workflow.rag.local_gateway import InMemoryRagGateway
from agent_workflow.rag.qdrant_gateway import QdrantRagGateway
from agent_workflow.security.approval import ApprovalGate, InMemoryApprovalStore
from agent_workflow.security.audit_store import InMemoryAuditStore
from agent_workflow.storage.postgres import PostgresApprovalStore, PostgresAuditStore
from agent_workflow.tools.executor import ToolExecutorRegistry
from agent_workflow.tools.idempotency import InMemoryIdempotencyStore, RedisIdempotencyStore
from agent_workflow.tools.loader import load_tool_specs
from agent_workflow.tools.registry import ToolRegistry


def _resolve_path(path: Path) -> Path:
    return path if path.is_absolute() else Path.cwd() / path


def build_default_orchestrator(settings: AppSettings | None = None) -> SessionOrchestrator:
    """Build orchestrator with real Redis/Postgres stores when configured."""

    settings = settings or get_settings()
    tool_specs = load_tool_specs(_resolve_path(settings.tools_config_path))
    tool_registry = ToolRegistry(tool_specs)
    executor_registry = ToolExecutorRegistry(tool_registry)

    grading_adapter = LocalGradingSystemAdapter()
    for tool_name, executor in build_grading_executors(grading_adapter).items():
        executor_registry.register(tool_name, executor)

    checkpoint_store = (
        RedisCheckpointStore(settings.redis_url)
        if settings.redis_url
        else InMemoryCheckpointStore()
    )
    idempotency_store = (
        RedisIdempotencyStore(settings.redis_url)
        if settings.redis_url
        else InMemoryIdempotencyStore()
    )

    postgres_dsn = settings.postgres_dsn.get_secret_value() if settings.postgres_dsn else None
    approval_store = (
        PostgresApprovalStore(postgres_dsn)
        if postgres_dsn
        else InMemoryApprovalStore()
    )
    audit_store = PostgresAuditStore(postgres_dsn) if postgres_dsn else InMemoryAuditStore()

    return SessionOrchestrator(
        checkpoint_store=checkpoint_store,
        tool_registry=tool_registry,
        executor_registry=executor_registry,
        approval_gate=ApprovalGate(approval_store),
        approval_store=approval_store,
        idempotency_store=idempotency_store,
        audit_store=audit_store,
    )


def build_default_langgraph_runtime(
    orchestrator: SessionOrchestrator,
    settings: AppSettings | None = None,
) -> LangGraphSessionRuntime | None:
    """Build LangGraph runtime if enabled."""

    settings = settings or get_settings()
    if not settings.enable_langgraph:
        return None
    return LangGraphSessionRuntime(orchestrator)


def build_default_rag_gateway(settings: AppSettings | None = None) -> RagGateway:
    """Build Qdrant-backed RAG when configured, otherwise local in-memory RAG."""

    settings = settings or get_settings()
    rag_config = load_rag_config(_resolve_path(settings.rag_config_path))

    # Build embedding model: use OpenAI-compatible API when api_key is available
    embedding_model: HashEmbeddingModel | OpenAICompatibleEmbeddingModel
    if settings.model_api_key:
        embedding_base_url = settings.embedding_base_url or settings.model_base_url
        embedding_model = OpenAICompatibleEmbeddingModel(
            base_url=embedding_base_url,
            model=settings.embedding_model_name,
            api_key=settings.model_api_key.get_secret_value(),
            dimension=settings.embedding_dimension,
        )
    else:
        embedding_model = HashEmbeddingModel(dimension=settings.embedding_dimension)

    # Build reranker if enabled
    reranker: CrossEncoderReranker | None = None
    if settings.reranker_enabled and settings.model_api_key:
        reranker = CrossEncoderReranker(
            base_url=settings.model_base_url,
            model=settings.model_name,
            api_key=settings.model_api_key.get_secret_value(),
        )

    if settings.qdrant_url:
        return QdrantRagGateway(
            url=settings.qdrant_url,
            config=rag_config,
            api_key=(
                settings.qdrant_api_key.get_secret_value()
                if settings.qdrant_api_key
                else None
            ),
            embedding_model=embedding_model,
            reranker=reranker,
            dimension=settings.embedding_dimension,
            text_collection=settings.rag_text_collection,
            visual_collection=settings.rag_visual_collection,
        )
    return InMemoryRagGateway(
        config=rag_config,
        embedding_model=embedding_model,
        reranker=reranker,
    )


def build_default_mcp_gateway(settings: AppSettings | None = None) -> StreamableHttpMcpGateway:
    """Build Streamable HTTP MCP gateway from configured server allowlists."""

    settings = settings or get_settings()
    config = load_mcp_gateway_config(_resolve_path(settings.mcp_config_path))
    return StreamableHttpMcpGateway(config)


def build_default_chat_client(settings: AppSettings | None = None) -> OpenAICompatibleChatClient:
    """Build the configured OpenAI-compatible chat client, restoring from cache if available."""

    from agent_workflow.config_cache import get_settings_cache

    settings = settings or get_settings()
    cached = get_settings_cache().get("model")
    if cached:
        from pydantic import SecretStr as _SecretStr

        return OpenAICompatibleChatClient(
            base_url=cached.get("base_url") or settings.model_base_url,
            model=cached.get("model") or settings.model_name,
            api_key=_SecretStr(cached["api_key"]) if cached.get("api_key") else settings.model_api_key,
            timeout_seconds=settings.model_timeout_seconds,
        )
    return OpenAICompatibleChatClient(
        base_url=settings.model_base_url,
        model=settings.model_name,
        api_key=settings.model_api_key,
        timeout_seconds=settings.model_timeout_seconds,
    )


def get_orchestrator(request: Request) -> SessionOrchestrator:
    """Return the process-local orchestrator attached to the app."""

    orchestrator = getattr(request.app.state, "orchestrator", None)
    if not isinstance(orchestrator, SessionOrchestrator):
        raise RuntimeError("orchestrator is not initialized")
    return orchestrator


def get_langgraph_runtime(request: Request) -> LangGraphSessionRuntime:
    """Return the LangGraph runtime attached to the app."""

    runtime = getattr(request.app.state, "langgraph_runtime", None)
    if not isinstance(runtime, LangGraphSessionRuntime):
        raise RuntimeError("langgraph runtime is not initialized")
    return runtime


def get_rag_gateway(request: Request) -> RagGateway:
    """Return the process-local RAG gateway."""

    gateway = getattr(request.app.state, "rag_gateway", None)
    if gateway is None:
        raise RuntimeError("rag gateway is not initialized")
    return cast(RagGateway, gateway)


def get_mcp_gateway(request: Request) -> StreamableHttpMcpGateway:
    """Return the process-local MCP gateway."""

    gateway = getattr(request.app.state, "mcp_gateway", None)
    if not isinstance(gateway, StreamableHttpMcpGateway):
        raise RuntimeError("mcp gateway is not initialized")
    return gateway


def get_chat_client(request: Request) -> OpenAICompatibleChatClient:
    """Return the process-local chat model client."""

    client = getattr(request.app.state, "chat_client", None)
    if not isinstance(client, OpenAICompatibleChatClient):
        raise RuntimeError("chat client is not initialized")
    return client
