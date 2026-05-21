from fastapi.testclient import TestClient

from agent_workflow.api.app import create_app


def test_api_runs_draft_tool_and_approval_flow() -> None:
    client = TestClient(create_app())

    draft_response = client.post(
        "/sessions/run",
        json={
            "user_id": "teacher-1",
            "message": "保存草稿",
            "tool_call": {
                "tool_name": "save_feedback_draft",
                "arguments": {
                    "submission_id": "submission-1",
                    "draft_revision": "api-r1",
                    "feedback_markdown": "API 草稿反馈。",
                },
            },
        },
    )
    assert draft_response.status_code == 200
    assert draft_response.json()["tool_result"]["status"] == "accepted"

    publish_response = client.post(
        "/sessions/run",
        json={
            "user_id": "teacher-1",
            "tool_call": {
                "tool_name": "publish_grade",
                "arguments": {
                    "submission_id": "submission-1",
                    "rubric_version": "v1",
                    "score": 91,
                    "feedback_markdown": "API 正式反馈。",
                },
            },
        },
    )
    assert publish_response.status_code == 200
    publish_payload = publish_response.json()
    assert publish_payload["approval_required"] is True

    approval_id = publish_payload["pending_approval"]["approval_id"]
    approval_response = client.post(
        f"/approvals/{approval_id}/decide",
        json={"approved_by": "reviewer-1", "approved": True, "reason": "复核通过"},
    )
    assert approval_response.status_code == 200
    assert approval_response.json()["tool_result"]["status"] == "accepted"
