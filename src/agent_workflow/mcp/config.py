"""Configuration loader for remote MCP servers."""

from pathlib import Path

import yaml
from pydantic import BaseModel, ConfigDict, Field


class McpServerConfig(BaseModel):
    """Remote MCP server allowlist and transport configuration."""

    model_config = ConfigDict(extra="forbid")

    enabled: bool = True
    transport: str = "streamable_http"
    base_url: str
    timeout_seconds: float = Field(default=30, gt=0)
    scopes: list[str] = Field(default_factory=list)
    allow_tools: list[str] = Field(default_factory=list)
    allow_resources: list[str] = Field(default_factory=list)
    allow_prompts: list[str] = Field(default_factory=list)


class McpGatewayConfig(BaseModel):
    """A named collection of MCP server configs."""

    model_config = ConfigDict(extra="forbid")

    servers: dict[str, McpServerConfig] = Field(default_factory=dict)


def load_mcp_gateway_config(path: Path) -> McpGatewayConfig:
    """Load MCP gateway configuration from YAML."""

    with path.open(encoding="utf-8") as file:
        payload = yaml.safe_load(file) or {}
    return McpGatewayConfig.model_validate(payload)
