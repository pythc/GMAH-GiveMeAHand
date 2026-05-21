import zipfile
from pathlib import Path

from fastapi.testclient import TestClient

from agent_workflow.api.app import create_app


def test_qq_onebot_webhook_and_archive_inspection(tmp_path: Path) -> None:
    archive_path = tmp_path / "project.zip"
    with zipfile.ZipFile(archive_path, "w") as archive:
        archive.writestr("README.md", "readme")
        archive.writestr("src/main.py", "print('ok')")

    client = TestClient(create_app())
    response = client.post(
        "/qq/onebot/webhook",
        json={
            "post_type": "message",
            "message_type": "group",
            "time": 1700000000,
            "group_id": 123,
            "user_id": 456,
            "message_id": 789,
            "message": [
                {"type": "text", "data": {"text": "分析压缩包"}},
                {
                    "type": "file",
                    "data": {"file": "project.zip", "path": str(archive_path), "size": 1024},
                },
            ],
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["normalized"]["conversation_id"] == "group:123"
    assert payload["archive_inspections"][0]["safe"] is True

    events = client.get("/qq/events").json()
    assert events[-1]["content"]["text"] == "分析压缩包"

    inspected = client.post("/qq/archive/inspect", json={"path": str(archive_path)}).json()
    extracted = client.post(
        "/qq/archive/extract",
        json={"path": str(archive_path), "destination_dir": str(tmp_path / "extract")},
    ).json()
    evaluated = client.post(
        "/qq/archive/evaluate",
        json={
            "path": str(archive_path),
            "destination_dir": str(tmp_path / "evaluate"),
            "topic_title": "QQ 上传课题",
            "topic_goal": "分析所有产物",
        },
    ).json()

    assert inspected["detected_artifacts"]["code_files"] == 1
    assert extracted["inspection"]["safe"] is True
    assert evaluated["evaluation"]["overall_score"] >= 0


def test_qq_download_and_send_routes(tmp_path: Path) -> None:
    source = tmp_path / "project.zip"
    source.write_bytes(b"zipdata")
    client = TestClient(create_app())

    downloaded = client.post(
        "/qq/files/download",
        json={
            "download_dir": str(tmp_path / "downloads"),
            "attachment": {
                "type": "file",
                "mime": "application/zip",
                "uri": str(source),
                "name": "project.zip",
            },
        },
    )
    send_failed = client.post(
        "/qq/send",
        json={"conversation_id": "bad", "message": "hello"},
    )

    assert downloaded.status_code == 200
    assert downloaded.json()["size_bytes"] == 7
    assert send_failed.status_code == 400


def test_qq_automation_settings_blacklist_and_text_evaluation() -> None:
    client = TestClient(create_app())

    settings = client.put(
        "/qq/automation/settings",
        json={
            "auto_evaluate_enabled": True,
            "auto_reply_enabled": False,
            "deep_review_enabled": False,
            "progress_report_level": "normal",
            "agent_system_prompt": "你是测试用 QQ 评价智能体。",
            "blacklist": [{"entry_type": "user", "value": "blocked"}],
        },
    )

    assert settings.status_code == 200
    assert settings.json()["auto_evaluate_enabled"] is True
    assert settings.json()["progress_report_level"] == "normal"
    assert settings.json()["agent_system_prompt"] == "你是测试用 QQ 评价智能体。"
    assert settings.json()["blacklist"][0]["value"] == "blocked"

    blocked = client.post(
        "/qq/onebot/webhook",
        json={
            "post_type": "message",
            "message_type": "private",
            "time": 1700000000,
            "user_id": "blocked",
            "message_id": "blocked-message",
            "message": "https://github.com/example/repo",
        },
    ).json()
    allowed = client.post(
        "/qq/onebot/webhook",
        json={
            "post_type": "message",
            "message_type": "private",
            "time": 1700000000,
            "user_id": "allowed",
            "message_id": "allowed-message",
            "message": "https://github.com/example/repo",
        },
    ).json()

    assert blocked["auto_actions"][0]["action"] == "blacklist"
    assert allowed["auto_actions"][0]["action"] == "evaluate_text"
    assert allowed["auto_actions"][0]["status"] == "success"
