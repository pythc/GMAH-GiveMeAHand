"""Load function tool specifications from JSON manifests."""

import json
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field

from agent_workflow.tools.schemas import FunctionToolSpec


class ToolManifest(BaseModel):
    """A versionable manifest that groups function tool specifications."""

    model_config = ConfigDict(extra="forbid")

    tools: list[FunctionToolSpec] = Field(default_factory=list)


def load_tool_manifest(path: Path) -> ToolManifest:
    """Load and validate a JSON tool manifest."""

    with path.open(encoding="utf-8") as file:
        payload = json.load(file)
    return ToolManifest.model_validate(payload)


def load_tool_specs(path: Path) -> list[FunctionToolSpec]:
    """Load tool specs from a manifest file."""

    return load_tool_manifest(path).tools
