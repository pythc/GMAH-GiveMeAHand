"""Test the Agent API endpoint through the FastAPI test client."""

from __future__ import annotations

import os
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from agent_workflow.api.app import create_app


REAL_API_KEY = os.environ.get("MODEL_API_KEY", "")
SKIP_INTEGRATION = not REAL_API_KEY or REAL_API_KEY == "replace-with-local-secret"


class TestAgentAPIEndpoint:
    """Test the /agent endpoints."""

    def test_agent_status(self):
        """Agent status endpoint works without API key."""
        app = create_app()
        client = TestClient(app)
        response = client.get("/agent/status")
        assert response.status_code == 200
        body = response.json()
        assert body["status"] == "ready"
        assert "react-loop" in body["engine"]

    @pytest.mark.skipif(SKIP_INTEGRATION, reason="MODEL_API_KEY not set")
    def test_agent_chat_endpoint(self):
        """Full agent chat via HTTP endpoint."""
        with patch.dict(os.environ, {"MODEL_API_KEY": REAL_API_KEY}):
            app = create_app()
            client = TestClient(app)

            response = client.post("/agent/chat", json={
                "message": "请获取 assignment-1 的作业信息。",
                "config": {
                    "max_steps": 8,
                    "enable_planning": False,
                    "enable_reflection": False,
                },
            })

            print(f"\nStatus: {response.status_code}")
            if response.status_code == 200:
                body = response.json()
                print(f"Answer: {body['answer'][:300]}")
                print(f"Tools: {body['tools_used']}")
                print(f"Steps: {body['steps_taken']}")
                print(f"LLM calls: {body['total_llm_calls']}")
                assert body["success"]
                assert "fetch_assignment" in body["tools_used"]
            else:
                print(f"Error: {response.text}")
                pytest.fail(f"API returned {response.status_code}")
