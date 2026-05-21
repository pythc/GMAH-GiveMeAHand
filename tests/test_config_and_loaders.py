from pathlib import Path

from agent_workflow.config import AppSettings
from agent_workflow.mcp.config import load_mcp_gateway_config
from agent_workflow.rag.config import load_rag_config


def test_app_settings_defaults_for_doubao_and_paths() -> None:
    settings = AppSettings()
    assert settings.model_base_url == "https://ark.cn-beijing.volces.com/api/v3"
    assert settings.model_name == "doubao-seed-2-0-code-preview-260215"
    assert settings.tools_config_path == Path("configs/tools.example.json")


def test_rag_config_loader_accepts_yaml(tmp_path: Path) -> None:
    path = tmp_path / "rag.yaml"
    path.write_text(
        """
collections:
  text:
    collection_name: custom_text
    chunk_size_tokens: 3
retrieval:
  fused_top_k: 2
""",
        encoding="utf-8",
    )

    config = load_rag_config(path)
    assert config.collections.text.collection_name == "custom_text"
    assert config.collections.text.chunk_size_tokens == 3
    assert config.retrieval.fused_top_k == 2


def test_mcp_config_loader_accepts_yaml(tmp_path: Path) -> None:
    path = tmp_path / "mcp.yaml"
    path.write_text(
        """
servers:
  grading:
    enabled: true
    transport: streamable_http
    base_url: http://localhost:8100/mcp
    allow_tools: [fetch_submission]
""",
        encoding="utf-8",
    )

    config = load_mcp_gateway_config(path)
    assert config.servers["grading"].base_url == "http://localhost:8100/mcp"
    assert config.servers["grading"].allow_tools == ["fetch_submission"]
