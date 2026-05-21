from pathlib import Path

from agent_workflow.tools.loader import load_tool_specs
from agent_workflow.tools.schemas import ApprovalPolicy, RiskLevel


def test_load_tool_specs_from_manifest() -> None:
    specs = load_tool_specs(Path("configs/tools.example.json"))
    names = {spec.name for spec in specs}
    assert {"fetch_assignment", "fetch_rubric", "fetch_submission"}.issubset(names)

    publish_grade = next(spec for spec in specs if spec.name == "publish_grade")
    assert publish_grade.risk_level is RiskLevel.HIGH
    assert publish_grade.approval_policy is ApprovalPolicy.HUMAN_REQUIRED
