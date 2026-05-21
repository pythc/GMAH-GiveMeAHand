import json
from types import SimpleNamespace
from typing import Any

import pytest

from agent_workflow.orchestrator.checkpoint import RedisCheckpointStore
from agent_workflow.orchestrator.state import ConversationMessage, MessageRole, SessionState
from agent_workflow.rag.models import IngestDocument, Modality, RetrievalQuery
from agent_workflow.rag.qdrant_gateway import QdrantRagGateway
from agent_workflow.security.audit import ApprovalRecord, AuditAction, AuditEvent
from agent_workflow.storage.postgres import PostgresApprovalStore, PostgresAuditStore
from agent_workflow.tools.idempotency import RedisIdempotencyStore
from agent_workflow.tools.schemas import ToolCallResult


class FakeRedisClient:
    data: dict[str, str] = {}

    @classmethod
    def from_url(cls, redis_url: str, *, decode_responses: bool) -> "FakeRedisClient":
        assert redis_url == "redis://test/0"
        assert decode_responses is True
        return cls()

    def get(self, key: str) -> str | None:
        return self.data.get(key)

    def set(self, key: str, value: str) -> None:
        self.data[key] = value


def test_redis_checkpoint_and_idempotency_stores(monkeypatch: pytest.MonkeyPatch) -> None:
    FakeRedisClient.data = {}
    monkeypatch.setitem(
        __import__("sys").modules,
        "redis",
        SimpleNamespace(Redis=FakeRedisClient),
    )

    checkpoint = RedisCheckpointStore("redis://test/0")
    state = SessionState(thread_id="thread-1")
    state.append_message(ConversationMessage(role=MessageRole.USER, content="hello"))
    checkpoint.save(state)
    loaded = checkpoint.load("thread-1")

    assert loaded is not None
    assert loaded.messages[0].content == "hello"

    idempotency = RedisIdempotencyStore("redis://test/0")
    result = ToolCallResult(tool_name="tool", accepted=True, output={"ok": True})
    idempotency.record("key-1", result)
    assert idempotency.get("key-1") == result


class FakeQdrantModels:
    class Distance:
        COSINE = "Cosine"

    class VectorParams:
        def __init__(self, *, size: int, distance: str) -> None:
            self.size = size
            self.distance = distance

    class PointStruct:
        def __init__(self, *, id: str, vector: list[float], payload: dict[str, Any]) -> None:
            self.id = id
            self.vector = vector
            self.payload = payload

    class MatchValue:
        def __init__(self, *, value: object) -> None:
            self.value = value

    class FieldCondition:
        def __init__(self, *, key: str, match: "FakeQdrantModels.MatchValue") -> None:
            self.key = key
            self.match = match

    class Filter:
        def __init__(self, *, must: list["FakeQdrantModels.FieldCondition"]) -> None:
            self.must = must


class FakeScoredPoint:
    def __init__(self, *, payload: dict[str, Any], score: float) -> None:
        self.payload = payload
        self.score = score


class FakeQdrantClient:
    collections: dict[str, list[FakeQdrantModels.PointStruct]] = {}

    def __init__(self, *, url: str, api_key: str | None = None) -> None:
        assert url == "http://qdrant.test"
        assert api_key is None

    def collection_exists(self, collection: str) -> bool:
        return collection in self.collections

    def create_collection(self, *, collection_name: str, vectors_config: object) -> None:
        self.collections[collection_name] = []

    def upsert(self, *, collection_name: str, points: list[FakeQdrantModels.PointStruct]) -> None:
        self.collections.setdefault(collection_name, []).extend(points)

    def search(
        self,
        *,
        collection_name: str,
        query_vector: list[float],
        query_filter: object | None,
        limit: int,
        with_payload: bool,
    ) -> list[FakeScoredPoint]:
        assert with_payload is True
        return [
            FakeScoredPoint(payload=point.payload, score=0.9)
            for point in self.collections.get(collection_name, [])[:limit]
        ]


def test_qdrant_rag_gateway_ingests_and_retrieves_with_fake_client(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    FakeQdrantClient.collections = {}
    modules = __import__("sys").modules
    monkeypatch.setitem(modules, "qdrant_client", SimpleNamespace(QdrantClient=FakeQdrantClient))
    monkeypatch.setitem(modules, "qdrant_client.models", FakeQdrantModels)

    gateway = QdrantRagGateway(
        url="http://qdrant.test",
        text_collection="text",
        visual_collection="visual",
    )
    ingest = gateway.ingest_documents([IngestDocument(source_id="doc", text="qdrant rag")])
    result = gateway.retrieve_text(RetrievalQuery(query="qdrant"))

    assert ingest.text_chunks == 1
    assert result.evidence[0].source_id == "doc"
    assert result.evidence[0].modality is Modality.TEXT


class FakeCursor:
    def __init__(self, db: dict[str, list[str]]) -> None:
        self.db = db
        self._rows: list[tuple[str]] = []

    def __enter__(self) -> "FakeCursor":
        return self

    def __exit__(self, exc_type: object, exc: object, tb: object) -> None:
        return None

    def execute(self, sql: str, params: tuple[object, ...] = ()) -> None:
        normalized_sql = " ".join(sql.split())
        if "INSERT INTO audit_events" in normalized_sql:
            self.db.setdefault("audit", []).append(str(params[4]))
        elif "SELECT payload::text FROM audit_events WHERE" in normalized_sql:
            trace_id = params[0]
            self._rows = [
                (payload,)
                for payload in self.db.get("audit", [])
                if json.loads(payload)["trace_id"] == trace_id
            ]
        elif "SELECT payload::text FROM audit_events" in normalized_sql:
            self._rows = [(payload,) for payload in self.db.get("audit", [])]
        elif "INSERT INTO approvals" in normalized_sql:
            self.db.setdefault("approvals", []).append(str(params[4]))
        elif "SELECT payload::text FROM approvals WHERE approval_id" in normalized_sql:
            approval_id = params[0]
            self._rows = [
                (payload,)
                for payload in self.db.get("approvals", [])
                if json.loads(payload)["approval_id"] == approval_id
            ]
        elif "UPDATE approvals" in normalized_sql:
            approval_id = params[2]
            self.db["approvals"] = [
                str(params[1]) if json.loads(payload)["approval_id"] == approval_id else payload
                for payload in self.db.get("approvals", [])
            ]
        elif "SELECT payload::text FROM approvals WHERE approved IS NULL" in normalized_sql:
            self._rows = [
                (payload,)
                for payload in self.db.get("approvals", [])
                if json.loads(payload)["approved"] is None
            ]

    def fetchall(self) -> list[tuple[str]]:
        return self._rows

    def fetchone(self) -> tuple[str] | None:
        return self._rows[0] if self._rows else None


class FakeConnection:
    def __init__(self, db: dict[str, list[str]]) -> None:
        self.db = db

    def __enter__(self) -> "FakeConnection":
        return self

    def __exit__(self, exc_type: object, exc: object, tb: object) -> None:
        return None

    def cursor(self) -> FakeCursor:
        return FakeCursor(self.db)


class FakeFactory:
    def __init__(self) -> None:
        self.db: dict[str, list[str]] = {}

    def connect(self) -> FakeConnection:
        return FakeConnection(self.db)


def test_postgres_audit_and_approval_stores_with_fake_connection() -> None:
    factory = FakeFactory()
    audit_store = PostgresAuditStore("postgresql://test")
    audit_store._factory = factory  # type: ignore[assignment]
    event = AuditEvent(
        action=AuditAction.TOOL_CALLED,
        actor_id="teacher",
        target="tool",
        trace_id="trace-1",
    )
    audit_store.append(event)
    assert audit_store.list_events("trace-1") == [event]

    approval_store = PostgresApprovalStore("postgresql://test")
    approval_store._factory = factory  # type: ignore[assignment]
    record = ApprovalRecord(
        approval_id="appr-1",
        tool_name="publish_grade",
        requested_by="teacher",
        thread_id="thread-1",
        trace_id="trace-1",
    )
    approval_store.create(record)
    assert approval_store.get("appr-1").approval_id == "appr-1"
    assert approval_store.list_pending()[0].approval_id == "appr-1"
    decided = approval_store.decide("appr-1", approved_by="reviewer", approved=True)
    assert decided.approved is True
