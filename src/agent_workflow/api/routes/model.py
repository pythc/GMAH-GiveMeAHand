"""Chat model HTTP routes."""

from typing import Annotated

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field, SecretStr

from agent_workflow.api.dependencies import get_chat_client
from agent_workflow.config_cache import get_settings_cache
from agent_workflow.llm.models import ChatCompletionRequest, ChatCompletionResult
from agent_workflow.llm.openai_compatible import OpenAICompatibleChatClient

router = APIRouter(prefix="/model", tags=["model"])
ChatClientDep = Annotated[OpenAICompatibleChatClient, Depends(get_chat_client)]


class ModelSettingsResponse(BaseModel):
    provider: str = "openai-compatible"
    base_url: str
    model: str
    api_key_configured: bool


class UpdateModelSettingsRequest(BaseModel):
    base_url: str | None = None
    model: str | None = None
    api_key: str | None = Field(default=None, min_length=1)


@router.get("/settings")
def get_model_settings(client: ChatClientDep) -> ModelSettingsResponse:
    return ModelSettingsResponse(
        base_url=client.base_url,
        model=client.model,
        api_key_configured=client.api_key_configured,
    )


@router.put("/settings")
def update_model_settings(
    request: Request,
    payload: UpdateModelSettingsRequest,
    client: ChatClientDep,
) -> ModelSettingsResponse:
    api_key = SecretStr(payload.api_key) if payload.api_key else client.api_key_secret
    updated = OpenAICompatibleChatClient(
        base_url=payload.base_url or client.base_url,
        model=payload.model or client.model,
        api_key=api_key,
    )
    request.app.state.chat_client = updated
    # Persist to cache
    get_settings_cache().set("model", {
        "base_url": updated.base_url,
        "model": updated.model,
        "api_key": api_key.get_secret_value() if api_key else None,
    })
    return ModelSettingsResponse(
        base_url=updated.base_url,
        model=updated.model,
        api_key_configured=updated.api_key_configured,
    )


@router.post("/chat")
def chat(request: ChatCompletionRequest, client: ChatClientDep) -> ChatCompletionResult:
    return client.chat(request)
