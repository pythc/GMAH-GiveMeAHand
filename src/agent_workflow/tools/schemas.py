"""Schemas for OpenAI-compatible function tool registration."""

from enum import StrEnum
from typing import Any

from jsonschema import Draft202012Validator
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class RiskLevel(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class ApprovalPolicy(StrEnum):
    NONE = "none"
    POLICY_BASED = "policy_based"
    HUMAN_REQUIRED = "human_required"


class FunctionToolSpec(BaseModel):
    """A strict JSON-schema based function tool definition."""

    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, pattern=r"^[a-zA-Z][a-zA-Z0-9_]{1,63}$")
    description: str = Field(min_length=1)
    strict: bool = True
    risk_level: RiskLevel = RiskLevel.LOW
    approval_policy: ApprovalPolicy = ApprovalPolicy.NONE
    idempotency_key_source: str | None = None
    parameters: dict[str, Any]

    @field_validator("parameters")
    @classmethod
    def validate_json_schema(cls, value: dict[str, Any]) -> dict[str, Any]:
        Draft202012Validator.check_schema(value)
        if value.get("type") != "object":
            raise ValueError("tool parameters must be an object JSON Schema")
        return value

    @model_validator(mode="after")
    def validate_safety_metadata(self) -> "FunctionToolSpec":
        if self.strict and self.parameters.get("additionalProperties") is not False:
            raise ValueError("strict tools must set additionalProperties=false")
        if self.risk_level is RiskLevel.HIGH:
            if self.approval_policy is not ApprovalPolicy.HUMAN_REQUIRED:
                raise ValueError("high risk tools require human approval")
            if not self.idempotency_key_source:
                raise ValueError("high risk tools require an idempotency key source")
        return self


class ToolCallRequest(BaseModel):
    tool_name: str
    arguments: dict[str, Any]
    call_id: str | None = None


class ToolCallResult(BaseModel):
    tool_name: str
    accepted: bool
    output: dict[str, Any] = Field(default_factory=dict)
    error: str | None = None
