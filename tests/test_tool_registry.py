import pytest

from agent_workflow.tools import ApprovalPolicy, FunctionToolSpec, RiskLevel, ToolRegistry
from agent_workflow.tools.registry import ToolRegistryError
from agent_workflow.tools.schemas import ToolCallRequest


def make_tool() -> FunctionToolSpec:
    return FunctionToolSpec(
        name="publish_grade",
        description="Publish an approved grade.",
        strict=True,
        risk_level=RiskLevel.HIGH,
        approval_policy=ApprovalPolicy.HUMAN_REQUIRED,
        idempotency_key_source="submission_id+rubric_version",
        parameters={
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "submission_id": {"type": "string"},
                "rubric_version": {"type": "string"},
                "score": {"type": "number"},
            },
            "required": ["submission_id", "rubric_version", "score"],
        },
    )


def test_high_risk_tool_requires_human_approval() -> None:
    with pytest.raises(ValueError):
        FunctionToolSpec(
            name="publish_grade",
            description="Publish grade without enough safety metadata.",
            risk_level=RiskLevel.HIGH,
            approval_policy=ApprovalPolicy.NONE,
            parameters={"type": "object", "additionalProperties": False},
        )


def test_tool_schema_rejects_non_object_and_non_strict_parameters() -> None:
    with pytest.raises(ValueError):
        FunctionToolSpec(name="bad_tool", description="Bad.", parameters={"type": "string"})
    with pytest.raises(ValueError):
        FunctionToolSpec(
            name="loose_tool",
            description="Loose.",
            strict=True,
            parameters={"type": "object", "additionalProperties": True},
        )
    with pytest.raises(ValueError):
        FunctionToolSpec(
            name="high_tool",
            description="High.",
            risk_level=RiskLevel.HIGH,
            approval_policy=ApprovalPolicy.HUMAN_REQUIRED,
            parameters={"type": "object", "additionalProperties": False},
        )


def test_registry_validates_arguments() -> None:
    registry = ToolRegistry([make_tool()])
    result = registry.execute_mock(
        ToolCallRequest(
            tool_name="publish_grade",
            arguments={"submission_id": "sub-1", "rubric_version": "v1", "score": 95},
        )
    )
    assert result.accepted is True
    assert result.output["approval_policy"] == ApprovalPolicy.HUMAN_REQUIRED


def test_registry_rejects_unknown_tool() -> None:
    registry = ToolRegistry()
    with pytest.raises(ToolRegistryError):
        registry.get("missing")
