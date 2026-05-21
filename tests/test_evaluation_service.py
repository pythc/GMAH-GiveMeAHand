import pytest

from agent_workflow.evaluation.models import ArtifactInput, ArtifactKind, ProjectEvaluationRequest
from agent_workflow.evaluation.service import ProjectEvaluationService


def make_request() -> ProjectEvaluationRequest:
    return ProjectEvaluationRequest(
        topic_title="多模态智能体评测系统",
        topic_goal="构建可复现的课题产物综合分析与评价系统",
        artifacts=[
            ArtifactInput(
                artifact_id="report-1",
                kind=ArtifactKind.REPORT,
                title="研究报告",
                text="本报告说明问题、目标、方法、实验、结果、结论、风险和局限。",
            ),
            ArtifactInput(
                artifact_id="paper-1",
                kind=ArtifactKind.PAPER,
                title="论文",
                text="摘要 方法 baseline 对比 消融 创新 贡献 DOI 引用 图 表。",
            ),
            ArtifactInput(
                artifact_id="ppt-1",
                kind=ArtifactKind.PRESENTATION,
                title="答辩 PPT",
                text="PPT slide 可视化 架构 结论。",
            ),
            ArtifactInput(
                artifact_id="video-1",
                kind=ArtifactKind.VIDEO,
                title="讲解视频",
                transcript="video transcript explains architecture and experiment result.",
            ),
            ArtifactInput(
                artifact_id="repo-1",
                kind=ArtifactKind.CODE_REPOSITORY,
                title="代码仓库",
                repository_summary=(
                    "README Dockerfile pytest mypy lint CI requirements security tests."
                ),
            ),
        ],
    )


def test_project_evaluation_service_scores_complete_artifacts() -> None:
    result = ProjectEvaluationService().evaluate(make_request())

    assert result.overall_score >= 40
    assert all(result.coverage.values())
    assert result.artifact_assessments
    assert {item.criterion_id for item in result.criterion_assessments} >= {
        "research_quality",
        "reproducibility",
        "code_quality",
    }
    assert result.next_steps[-1] == "将所有产物摄取进 RAG，并为每条评价保留引用证据。"


def test_project_evaluation_service_flags_missing_artifacts() -> None:
    request = ProjectEvaluationRequest(
        topic_title="缺少代码的课题",
        topic_goal="分析材料完整性",
        artifacts=[
            ArtifactInput(
                artifact_id="report-1",
                kind=ArtifactKind.REPORT,
                title="报告",
                text="只有报告，包含目标和结论。",
            )
        ],
    )

    result = ProjectEvaluationService().evaluate(request)

    assert result.coverage["代码仓库"] is False
    assert any("缺少关键产物" in item for item in result.weaknesses)
    assert any("补齐代码仓库" in item for item in result.next_steps)


def test_artifact_requires_reviewable_content() -> None:
    with pytest.raises(ValueError):
        ArtifactInput(artifact_id="empty", kind=ArtifactKind.OTHER, title="空产物")
