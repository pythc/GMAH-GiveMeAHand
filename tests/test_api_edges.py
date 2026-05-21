from fastapi.testclient import TestClient

from agent_workflow.api.app import create_app


def test_session_create_and_get_roundtrip() -> None:
    client = TestClient(create_app())
    created = client.post("/sessions", json={"user_id": "u-1"})
    assert created.status_code == 201

    thread_id = created.json()["thread_id"]
    fetched = client.get(f"/sessions/{thread_id}")
    assert fetched.status_code == 200
    assert fetched.json()["user_id"] == "u-1"


def test_session_get_returns_404_for_missing_thread() -> None:
    client = TestClient(create_app())
    response = client.get("/sessions/missing")
    assert response.status_code == 404


def test_list_tools_route_returns_registered_tools() -> None:
    client = TestClient(create_app())
    response = client.get("/sessions/tools/list")
    assert response.status_code == 200
    names = {tool["name"] for tool in response.json()}
    assert "publish_grade" in names
    assert "save_feedback_draft" in names


def test_approval_pending_route_returns_empty_list_initially() -> None:
    client = TestClient(create_app())
    response = client.get("/approvals/pending")
    assert response.status_code == 200
    assert response.json() == []


def test_run_langgraph_route_executes_tool() -> None:
    client = TestClient(create_app())
    response = client.post(
        "/sessions/run-langgraph",
        json={
            "user_id": "teacher-1",
            "tool_call": {
                "tool_name": "fetch_submission",
                "arguments": {"submission_id": "submission-1"},
            },
        },
    )
    assert response.status_code == 200
    assert response.json()["tool_result"]["status"] == "accepted"
