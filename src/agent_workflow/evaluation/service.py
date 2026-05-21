"""Deterministic evaluator for research project artifacts."""

import re
from collections import Counter
from collections.abc import Iterable

from agent_workflow.evaluation.models import (
    ArtifactAssessment,
    ArtifactInput,
    ArtifactKind,
    CriterionAssessment,
    EvaluationRubric,
    ProjectEvaluationRequest,
    ProjectEvaluationResult,
    RubricCriterion,
)

DEFAULT_RUBRIC = EvaluationRubric(
    name="Research Artifact Review Rubric",
    criteria=[
        RubricCriterion(
            criterion_id="research_quality",
            name="研究问题与论证质量",
            description="课题目标、问题定义、方法选择、实验论证与结论是否清晰可信。",
            weight=0.18,
        ),
        RubricCriterion(
            criterion_id="technical_depth",
            name="技术深度与实现完整性",
            description="架构、算法、系统实现、实验设计与工程细节是否充分。",
            weight=0.16,
        ),
        RubricCriterion(
            criterion_id="evidence_traceability",
            name="证据链与可追溯性",
            description="报告、论文、PPT、视频、代码、数据之间是否能相互印证。",
            weight=0.14,
        ),
        RubricCriterion(
            criterion_id="reproducibility",
            name="可复现性",
            description="是否提供环境、数据、脚本、Docker、实验日志与复现实验说明。",
            weight=0.14,
        ),
        RubricCriterion(
            criterion_id="communication",
            name="表达与展示质量",
            description="写作结构、图表、PPT、视频讲解与结论表达是否清晰。",
            weight=0.12,
        ),
        RubricCriterion(
            criterion_id="code_quality",
            name="代码质量与仓库治理",
            description="代码结构、测试、CI、类型检查、文档、依赖管理与安全治理。",
            weight=0.12,
        ),
        RubricCriterion(
            criterion_id="innovation",
            name="创新性与对比分析",
            description="是否说明创新点、基线对比、消融实验、局限与改进空间。",
            weight=0.08,
        ),
        RubricCriterion(
            criterion_id="risk_ethics",
            name="风险、伦理与安全",
            description="是否识别隐私、安全、偏差、合规、滥用与局限性风险。",
            weight=0.06,
        ),
    ],
)

EXPECTED_KINDS = {
    ArtifactKind.REPORT: "报告",
    ArtifactKind.PAPER: "论文",
    ArtifactKind.PRESENTATION: "PPT/演示材料",
    ArtifactKind.VIDEO: "视频/答辩讲解",
    ArtifactKind.CODE_REPOSITORY: "代码仓库",
}

KEYWORDS = {
    "research_quality": [
        "问题",
        "目标",
        "方法",
        "实验",
        "结果",
        "结论",
        "hypothesis",
        "method",
    ],
    "technical_depth": ["架构", "算法", "实现", "系统", "benchmark", "ablation", "pipeline"],
    "evidence_traceability": [
        "引用",
        "doi",
        "图",
        "表",
        "附录",
        "commit",
        "artifact",
        "dataset",
    ],
    "reproducibility": [
        "readme",
        "docker",
        "requirements",
        "复现",
        "seed",
        "脚本",
        "test",
        "pytest",
    ],
    "communication": ["摘要", "目录", "结论", "可视化", "ppt", "slide", "video", "transcript"],
    "code_quality": ["test", "ci", "lint", "mypy", "typing", "dockerfile", "安全", "依赖"],
    "innovation": ["创新", "贡献", "baseline", "对比", "消融", "novel", "limitation"],
    "risk_ethics": ["风险", "隐私", "安全", "合规", "偏差", "伦理", "limitations", "security"],
}

SUGGESTIONS = {
    "research_quality": "补充明确研究问题、方法选择理由、实验假设和结论边界。",
    "technical_depth": "补充系统架构图、关键算法说明、参数设置和复杂度/性能分析。",
    "evidence_traceability": "建立报告、论文、PPT、视频、代码和数据之间的引用映射。",
    "reproducibility": "补充 README、环境锁定、Docker、数据路径、运行脚本和复现实验日志。",
    "communication": "优化摘要、目录、图表说明、PPT 叙事和视频讲解稿。",
    "code_quality": "补充测试、CI、lint、类型检查、依赖安全扫描和模块化说明。",
    "innovation": "明确创新点，增加基线对比、消融实验和局限性讨论。",
    "risk_ethics": "补充隐私、安全、偏差、合规、滥用场景和缓解措施。",
}


class ProjectEvaluationService:
    """Evaluate research artifacts using a rubric and transparent heuristics."""

    def default_rubric(self) -> EvaluationRubric:
        return DEFAULT_RUBRIC

    def evaluate(self, request: ProjectEvaluationRequest) -> ProjectEvaluationResult:
        rubric = request.rubric or DEFAULT_RUBRIC
        joined_text = "\n".join(_artifact_text(artifact) for artifact in request.artifacts).lower()
        artifact_counts = Counter(artifact.kind for artifact in request.artifacts)
        coverage = {label: kind in artifact_counts for kind, label in EXPECTED_KINDS.items()}
        artifact_assessments = [_assess_artifact(artifact) for artifact in request.artifacts]
        criterion_assessments = [
            _score_criterion(criterion, joined_text, artifact_counts, coverage)
            for criterion in rubric.criteria
        ]
        overall_score = round(
            sum(item.score * item.weight for item in criterion_assessments),
            2,
        )
        strengths = _collect_strengths(criterion_assessments, coverage)
        weaknesses = _collect_weaknesses(criterion_assessments, coverage)
        recommendations = _collect_recommendations(criterion_assessments)

        return ProjectEvaluationResult(
            topic_title=request.topic_title,
            overall_score=overall_score,
            summary=_summary(request.topic_title, overall_score, coverage),
            coverage=coverage,
            artifact_assessments=artifact_assessments,
            criterion_assessments=criterion_assessments,
            strengths=strengths,
            weaknesses=weaknesses,
            recommendations=recommendations,
            next_steps=_next_steps(coverage, criterion_assessments),
        )


def _artifact_text(artifact: ArtifactInput) -> str:
    return "\n".join(
        part
        for part in [
            artifact.title,
            artifact.uri or "",
            artifact.text or "",
            artifact.transcript or "",
            artifact.repository_summary or "",
            str(artifact.metadata),
        ]
        if part
    )


def _assess_artifact(artifact: ArtifactInput) -> ArtifactAssessment:
    text = _artifact_text(artifact).lower()
    words = re.findall(r"[\w\u4e00-\u9fff]+", text)
    signals: list[str] = []
    missing: list[str] = []

    for signal, keywords in {
        "包含实验/结果信息": ["实验", "result", "benchmark", "结果"],
        "包含复现信息": ["docker", "readme", "requirements", "复现"],
        "包含风险/局限讨论": ["风险", "局限", "limitation", "security"],
    }.items():
        if any(keyword in text for keyword in keywords):
            signals.append(signal)
        else:
            missing.append(signal)

    return ArtifactAssessment(
        artifact_id=artifact.artifact_id,
        kind=artifact.kind,
        title=artifact.title,
        word_count=len(words),
        evidence_signals=signals,
        missing_signals=missing,
    )


def _score_criterion(
    criterion: RubricCriterion,
    text: str,
    artifact_counts: Counter[ArtifactKind],
    coverage: dict[str, bool],
) -> CriterionAssessment:
    keywords = KEYWORDS.get(criterion.criterion_id, [])
    hits = [keyword for keyword in keywords if keyword.lower() in text]
    # Score purely based on evidence found — no artificial base score
    score = min(len(hits), 8) * 12.5
    evidence = [f"命中信号：{keyword}" for keyword in hits[:8]]
    issues: list[str] = []

    missing_code = artifact_counts[ArtifactKind.CODE_REPOSITORY] == 0
    if criterion.criterion_id == "code_quality" and missing_code:
        score *= 0.4
        issues.append("未提供代码仓库，难以评价工程质量与可复现性。")
    if criterion.criterion_id == "communication":
        if artifact_counts[ArtifactKind.PRESENTATION] == 0:
            score -= 10
            issues.append("未提供 PPT/演示材料。")
        if artifact_counts[ArtifactKind.VIDEO] == 0:
            score -= 10
            issues.append("未提供视频或讲解稿。")
    if criterion.criterion_id == "evidence_traceability":
        missing_labels = [label for label, present in coverage.items() if not present]
        if missing_labels:
            score -= min(25, len(missing_labels) * 5)
            issues.append(f"产物覆盖不完整：缺少 {', '.join(missing_labels)}。")
    lacks_repro_docs = "docker" not in text and "readme" not in text
    if criterion.criterion_id == "reproducibility" and lacks_repro_docs:
        score -= 15
        issues.append("缺少 README/Docker/环境说明等关键复现材料。")

    if not hits:
        issues.append("未发现该维度的明确证据。")

    score = round(max(0, min(100, score)), 2)
    suggestions = [] if score >= 80 else [SUGGESTIONS.get(criterion.criterion_id, "补充证据。")]
    return CriterionAssessment(
        criterion_id=criterion.criterion_id,
        name=criterion.name,
        score=score,
        weight=criterion.weight,
        evidence=evidence,
        issues=issues,
        suggestions=suggestions,
    )


def _collect_strengths(
    assessments: Iterable[CriterionAssessment],
    coverage: dict[str, bool],
) -> list[str]:
    strengths = [
        f"{item.name} 表现较好（{item.score:.1f}）。"
        for item in assessments
        if item.score >= 80
    ]
    if all(coverage.values()):
        strengths.append("核心产物类型覆盖完整，具备综合评审基础。")
    return strengths or ["已提供可分析产物，可作为后续精评基础。"]


def _collect_weaknesses(
    assessments: Iterable[CriterionAssessment],
    coverage: dict[str, bool],
) -> list[str]:
    weaknesses = [
        f"{item.name} 证据不足（{item.score:.1f}）。"
        for item in assessments
        if item.score < 60
    ]
    for label, present in coverage.items():
        if not present:
            weaknesses.append(f"缺少关键产物：{label}。")
    return weaknesses


def _collect_recommendations(assessments: Iterable[CriterionAssessment]) -> list[str]:
    recommendations: list[str] = []
    for item in assessments:
        recommendations.extend(item.suggestions)
    return list(dict.fromkeys(recommendations))[:8]


def _next_steps(coverage: dict[str, bool], assessments: list[CriterionAssessment]) -> list[str]:
    steps = [f"补齐{label}。" for label, present in coverage.items() if not present]
    low = sorted(assessments, key=lambda item: item.score)[:3]
    steps.extend(f"优先改进：{item.name}。" for item in low if item.score < 75)
    steps.append("将所有产物摄取进 RAG，并为每条评价保留引用证据。")
    return list(dict.fromkeys(steps))


def _summary(topic_title: str, score: float, coverage: dict[str, bool]) -> str:
    missing = [label for label, present in coverage.items() if not present]
    if score >= 80:
        level = "整体质量较高"
    elif score >= 65:
        level = "具备较好基础，但仍需补强证据链"
    else:
        level = "当前材料不足以支撑高置信综合评价"
    missing_text = "；缺少" + "、".join(missing) if missing else "；核心产物覆盖完整"
    return f"课题《{topic_title}》{level}{missing_text}。"
