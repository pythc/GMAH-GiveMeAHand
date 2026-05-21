"""Application configuration models."""

from pathlib import Path

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class AppSettings(BaseSettings):
    """Typed application settings loaded from environment variables."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        populate_by_name=True,
    )

    app_env: str = Field(default="local", validation_alias="APP_ENV")
    log_level: str = Field(default="INFO", validation_alias="LOG_LEVEL")
    api_host: str = Field(default="0.0.0.0", validation_alias="API_HOST")
    api_port: int = Field(default=8080, validation_alias="API_PORT")

    model_provider: str = Field(default="openai-compatible", validation_alias="MODEL_PROVIDER")
    model_base_url: str = Field(
        default="https://ark.cn-beijing.volces.com/api/v3",
        validation_alias="MODEL_BASE_URL",
    )
    model_name: str = Field(
        default="doubao-seed-2-0-code-preview-260215",
        validation_alias="MODEL_NAME",
    )
    model_api_key: SecretStr | None = Field(default=None, validation_alias="MODEL_API_KEY")
    model_timeout_seconds: float = Field(default=180, validation_alias="MODEL_TIMEOUT_SECONDS")

    redis_url: str | None = Field(default=None, validation_alias="REDIS_URL")
    postgres_dsn: SecretStr | None = Field(default=None, validation_alias="POSTGRES_DSN")
    qdrant_url: str | None = Field(default=None, validation_alias="QDRANT_URL")
    qdrant_api_key: SecretStr | None = Field(default=None, validation_alias="QDRANT_API_KEY")
    minio_endpoint: str | None = Field(default=None, validation_alias="MINIO_ENDPOINT")
    minio_bucket: str | None = Field(default=None, validation_alias="MINIO_BUCKET")

    enable_langgraph: bool = Field(default=True, validation_alias="ENABLE_LANGGRAPH")
    embedding_dimension: int = Field(default=64, validation_alias="EMBEDDING_DIMENSION")
    embedding_model_name: str = Field(
        default="text-embedding-3-small",
        validation_alias="EMBEDDING_MODEL_NAME",
    )
    embedding_base_url: str | None = Field(
        default=None,
        validation_alias="EMBEDDING_BASE_URL",
    )
    reranker_enabled: bool = Field(default=False, validation_alias="RERANKER_ENABLED")
    rag_text_collection: str = Field(default="agent_text", validation_alias="RAG_TEXT_COLLECTION")
    rag_visual_collection: str = Field(
        default="agent_visual",
        validation_alias="RAG_VISUAL_COLLECTION",
    )

    onebot_ws_url: str | None = Field(default=None, validation_alias="ONEBOT_WS_URL")
    onebot_ws_reconnect_max_seconds: int = Field(
        default=60,
        validation_alias="ONEBOT_WS_RECONNECT_MAX_SECONDS",
    )

    tools_config_path: Path = Field(
        default=Path("configs/tools.example.json"),
        validation_alias="TOOLS_CONFIG_PATH",
    )
    mcp_config_path: Path = Field(
        default=Path("configs/mcp-servers.example.yaml"),
        validation_alias="MCP_CONFIG_PATH",
    )
    rag_config_path: Path = Field(
        default=Path("configs/rag.example.yaml"),
        validation_alias="RAG_CONFIG_PATH",
    )

    # Authentication settings
    auth_enabled: bool = Field(default=False, validation_alias="AUTH_ENABLED")
    jwt_secret_key: SecretStr = Field(
        default="agent-workflow-dev-secret-change-in-production",
        validation_alias="JWT_SECRET_KEY",
    )
    admin_username: str = Field(default="admin", validation_alias="ADMIN_USERNAME")
    admin_password: SecretStr = Field(default="admin", validation_alias="ADMIN_PASSWORD")
    api_keys: str = Field(default="", validation_alias="API_KEYS")


def get_settings() -> AppSettings:
    """Return application settings without exposing secret values."""

    return AppSettings()
