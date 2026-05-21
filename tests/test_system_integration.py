"""Integration tests for evaluation workflow, queue, PDF, and activity logs."""

import json
import threading
import time
from pathlib import Path

from fastapi.testclient import TestClient

from agent_workflow.api.app import create_app
from agent_workflow.channels.onebot.adapter import OneBotAdapter
from agent_workflow.channels.onebot.models import OneBotEvent, OneBotMessageSegment
from agent_workflow.config_cache import SettingsCache
from agent_workflow.evaluation.history import ReviewHistoryStore
from agent_workflow.evaluation.pdf_report import generate_evaluation_pdf
from agent_workflow.evaluation.repository_agent import _extract_json_object
from agent_workflow.evaluation.tool_log import ActivityLogStore, LogKind, get_tool_log_store


class TestJsonExtraction:
    """Test robust JSON extraction from model output."""

    def test_simple_json(self) -> None:
        result = _extract_json_object('{"tool": "test", "arguments": {}}')
        assert result == {"tool": "test", "arguments": {}}

    def test_nested_braces_in_value(self) -> None:
        text = json.dumps({"tool": "update", "arguments": {"review": "has {braces} ok"}})
        result = _extract_json_object(text)
        assert result["tool"] == "update"
        assert "{braces}" in result["arguments"]["review"]

    def test_prefix_and_suffix(self) -> None:
        result = _extract_json_object('Sure! {"tool": "x"} Done.')
        assert result == {"tool": "x"}

    def test_no_json(self) -> None:
        assert _extract_json_object("no json") == {}
        assert _extract_json_object("") == {}

    def test_newlines_in_value(self) -> None:
        text = json.dumps({"tool": "final_answer", "arguments": {"message": "line1\nline2"}})
        result = _extract_json_object(text)
        assert result["tool"] == "final_answer"
        assert "\n" in result["arguments"]["message"]

    def test_chinese_content(self) -> None:
        text = json.dumps({"tool": "send_progress", "arguments": {"message": "已克隆仓库"}})
        result = _extract_json_object(text)
        assert result["arguments"]["message"] == "已克隆仓库"


class TestActivityLogStore:
    """Test the shared activity log store."""

    def test_log_tool_call(self) -> None:
        store = ActivityLogStore(max_entries=100)
        store.log_tool_call(
            session_id="s1", tool="clone_repository",
            arguments={"url": "https://github.com/test"},
            result={"ok": True},
        )
        logs = store.list()
        assert len(logs) == 1
        assert logs[0].kind == LogKind.TOOL_CALL
        assert logs[0].tool == "clone_repository"

    def test_log_model_request_response(self) -> None:
        store = ActivityLogStore(max_entries=100)
        store.log_model_request(session_id="s1", model="test-model", messages_count=3)
        store.log_model_response(
            session_id="s1", model="test-model", content="hello", usage={"tokens": 10}
        )
        logs = store.list(kind=LogKind.MODEL_RESPONSE)
        assert len(logs) == 1
        assert logs[0].content == "hello"

    def test_filter_by_session(self) -> None:
        store = ActivityLogStore(max_entries=100)
        store.log_tool_call(session_id="a", tool="t1", arguments={}, result={"ok": True})
        store.log_tool_call(session_id="b", tool="t2", arguments={}, result={"ok": True})
        assert len(store.list(session_id="a")) == 1
        assert len(store.list(session_id="b")) == 1

    def test_max_entries_cap(self) -> None:
        store = ActivityLogStore(max_entries=5)
        for i in range(10):
            store.log_tool_call(
                session_id="s", tool=f"t{i}", arguments={}, result={"ok": True}
            )
        assert store.count == 5
        assert store.list()[0].tool == "t5"


class TestPdfGeneration:
    """Test PDF report generation."""

    def test_basic_pdf(self) -> None:
        text = "【项目名称】\n测试项目\n\n【综合评分】\n7/10\n\n普通文本行"
        path = generate_evaluation_pdf(text, "test_basic.pdf")
        assert path.exists()
        assert path.stat().st_size > 1000

    def test_empty_text(self) -> None:
        path = generate_evaluation_pdf("", "test_empty.pdf")
        assert path.exists()

    def test_long_text(self) -> None:
        text = "评测内容\n" * 500
        path = generate_evaluation_pdf(text, "test_long.pdf")
        assert path.exists()
        assert path.stat().st_size > 5000


class TestSettingsCache:
    """Test settings cache persistence."""

    def test_read_write(self, tmp_path: Path) -> None:
        cache = SettingsCache(tmp_path / "test_cache.json")
        cache.set("model", {"key": "value"})
        assert cache.get("model") == {"key": "value"}

    def test_corrupt_file(self, tmp_path: Path) -> None:
        path = tmp_path / "corrupt.json"
        path.write_text("not json {{{")
        cache = SettingsCache(path)
        assert cache.get("anything") is None

    def test_missing_file(self, tmp_path: Path) -> None:
        cache = SettingsCache(tmp_path / "missing.json")
        assert cache.get("x") is None
        cache.set("x", {"ok": True})
        cache2 = SettingsCache(tmp_path / "missing.json")
        assert cache2.get("x") == {"ok": True}


class TestOneBotAtParsing:
    """Test @ mention segment parsing."""

    def test_at_segment_preserved_in_text(self) -> None:
        adapter = OneBotAdapter()
        event = OneBotEvent(
            post_type="message", message_type="group",
            time=1, group_id=123, user_id=456, self_id=789, message_id=1,
            sender=None,
            message=[
                OneBotMessageSegment(type="at", data={"qq": "789"}),
                OneBotMessageSegment(type="text", data={"text": " hello"}),
            ],
        )
        normalized = adapter.normalize(event)
        assert "789" in (normalized.content.text or "")
        assert "hello" in (normalized.content.text or "")


class TestWebhookMetaEvent:
    """Test that heartbeat/meta events don't crash the webhook."""

    def test_heartbeat_accepted(self) -> None:
        client = TestClient(create_app())
        r = client.post("/qq/onebot/webhook", json={
            "post_type": "meta_event",
            "meta_event_type": "heartbeat",
            "time": 1,
        })
        assert r.status_code == 200
        assert r.json()["status"] == "ignored"

    def test_lifecycle_accepted(self) -> None:
        client = TestClient(create_app())
        r = client.post("/qq/onebot/webhook", json={
            "post_type": "meta_event",
            "meta_event_type": "lifecycle",
            "time": 1,
        })
        assert r.status_code == 200


class TestEvaluationEndpoints:
    """Test evaluation API endpoints."""

    def test_history_list(self) -> None:
        client = TestClient(create_app())
        r = client.get("/evaluation/history")
        assert r.status_code == 200
        assert isinstance(r.json(), list)

    def test_tool_logs_with_kind_filter(self) -> None:
        client = TestClient(create_app())
        r = client.get("/evaluation/tool-logs?kind=model_response&limit=10")
        assert r.status_code == 200

    def test_references_list(self) -> None:
        client = TestClient(create_app())
        r = client.get("/evaluation/references")
        assert r.status_code == 200
        assert "references" in r.json()

    def test_review_requires_source(self) -> None:
        client = TestClient(create_app())
        r = client.post("/evaluation/review", json={
            "topic_title": "test", "topic_goal": "test"
        })
        # Should fail without source_url or archive_path
        assert r.status_code in (400, 500)

    def test_queue_status(self) -> None:
        client = TestClient(create_app())
        r = client.get("/qq/queue")
        assert r.status_code == 200
        data = r.json()
        assert "busy" in data
        assert "queue_length" in data


class TestHistoryStore:
    """Test XLSX history store."""

    def test_get_nonexistent(self, tmp_path: Path) -> None:
        store = ReviewHistoryStore(tmp_path / "test.xlsx")
        assert store.get("https://no.exist") is None

    def test_update_and_get(self, tmp_path: Path) -> None:
        store = ReviewHistoryStore(tmp_path / "test.xlsx")
        result = store.update(
            repo_url="https://github.com/test/repo",
            topic_name="Test Topic",
            review="Good work",
            score=8.0,
            improved=True,
        )
        assert result.updated is True
        record = store.get("https://github.com/test/repo")
        assert record is not None
        assert record.score == 8.0
        assert record.review_count == 1

    def test_no_update_when_not_improved(self, tmp_path: Path) -> None:
        store = ReviewHistoryStore(tmp_path / "test.xlsx")
        store.update(
            repo_url="https://github.com/test/repo",
            topic_name="Test", review="First", score=7.0, improved=True,
        )
        result = store.update(
            repo_url="https://github.com/test/repo",
            topic_name="Test", review="Second", score=7.0, improved=False,
        )
        assert result.updated is False
        record = store.get("https://github.com/test/repo")
        assert record is not None
        assert record.review == "First"  # Not updated
