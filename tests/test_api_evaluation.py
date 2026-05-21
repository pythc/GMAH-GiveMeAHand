from fastapi.testclient import TestClient

from agent_workflow.api.app import create_app


def test_evaluation_api_returns_default_rubric_and_analysis() -> None:
    client = TestClient(create_app())

    rubric = client.get("/evaluation/rubric/default")
    assert rubric.status_code == 200
    assert rubric.json()["criteria"]

    response = client.post(
        "/evaluation/analyze",
        json={
            "topic_title": "智能体课题",
            "topic_goal": "评价所有课题产物",
            "artifacts": [
                {
                    "artifact_id": "report-1",
                    "kind": "report",
                    "title": "研究报告",
                    "text": "目标 方法 实验 结果 结论 风险",
                },
                {
                    "artifact_id": "repo-1",
                    "kind": "code_repository",
                    "title": "代码仓库",
                    "repository_summary": "README Docker pytest tests lint",
                },
            ],
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["overall_score"] >= 0
    assert payload["criterion_assessments"]
    assert payload["coverage"]["报告"] is True
