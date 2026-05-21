"""Postgres-backed stores for approvals and audit events."""

import importlib
from typing import Any

from agent_workflow.security.approval import ApprovalError
from agent_workflow.security.audit import ApprovalRecord, AuditEvent


class PostgresConnectionFactory:
    """Create psycopg connections from a DSN only when needed."""

    def __init__(self, dsn: str) -> None:
        self._dsn = dsn

    def connect(self) -> Any:
        psycopg = importlib.import_module("psycopg")
        return psycopg.connect(self._dsn)


class PostgresAuditStore:
    """Append-only audit event store using Postgres JSONB payloads."""

    def __init__(self, dsn: str) -> None:
        self._factory = PostgresConnectionFactory(dsn)
        self._initialized = False

    def append(self, event: AuditEvent) -> None:
        self._ensure_schema()
        with self._factory.connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO audit_events (trace_id, action, actor_id, target, payload)
                    VALUES (%s, %s, %s, %s, %s::jsonb)
                    """,
                    (
                        event.trace_id,
                        event.action.value,
                        event.actor_id,
                        event.target,
                        event.model_dump_json(),
                    ),
                )

    def list_events(self, trace_id: str | None = None) -> list[AuditEvent]:
        self._ensure_schema()
        with self._factory.connect() as conn:
            with conn.cursor() as cur:
                if trace_id is None:
                    cur.execute("SELECT payload::text FROM audit_events ORDER BY id ASC")
                else:
                    cur.execute(
                        """
                        SELECT payload::text
                        FROM audit_events
                        WHERE trace_id = %s
                        ORDER BY id ASC
                        """,
                        (trace_id,),
                    )
                return [AuditEvent.model_validate_json(row[0]) for row in cur.fetchall()]

    def _ensure_schema(self) -> None:
        if self._initialized:
            return
        with self._factory.connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    CREATE TABLE IF NOT EXISTS audit_events (
                        id BIGSERIAL PRIMARY KEY,
                        trace_id TEXT NOT NULL,
                        action TEXT NOT NULL,
                        actor_id TEXT NOT NULL,
                        target TEXT NOT NULL,
                        payload JSONB NOT NULL,
                        created_at TIMESTAMPTZ DEFAULT now()
                    )
                    """
                )
                cur.execute(
                    "CREATE INDEX IF NOT EXISTS idx_audit_events_trace_id ON audit_events(trace_id)"
                )
        self._initialized = True


class PostgresApprovalStore:
    """Approval store using Postgres JSONB payloads."""

    def __init__(self, dsn: str) -> None:
        self._factory = PostgresConnectionFactory(dsn)
        self._initialized = False

    def create(self, record: ApprovalRecord) -> ApprovalRecord:
        self._ensure_schema()
        with self._factory.connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO approvals (approval_id, thread_id, tool_name, approved, payload)
                    VALUES (%s, %s, %s, %s, %s::jsonb)
                    """,
                    (
                        record.approval_id,
                        record.thread_id,
                        record.tool_name,
                        record.approved,
                        record.model_dump_json(),
                    ),
                )
        return record.model_copy(deep=True)

    def get(self, approval_id: str) -> ApprovalRecord:
        self._ensure_schema()
        with self._factory.connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT payload::text FROM approvals WHERE approval_id = %s",
                    (approval_id,),
                )
                row = cur.fetchone()
        if row is None:
            raise ApprovalError(f"unknown approval: {approval_id}")
        return ApprovalRecord.model_validate_json(row[0])

    def decide(
        self,
        approval_id: str,
        *,
        approved_by: str,
        approved: bool,
        reason: str | None = None,
    ) -> ApprovalRecord:
        from datetime import UTC, datetime

        record = self.get(approval_id)
        if record.approved is not None:
            raise ApprovalError(f"approval already decided: {approval_id}")
        decided = record.model_copy(
            update={
                "approved_by": approved_by,
                "approved": approved,
                "reason": reason,
                "decided_at": datetime.now(UTC),
            },
            deep=True,
        )
        with self._factory.connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    UPDATE approvals
                    SET approved = %s, payload = %s::jsonb, decided_at = now()
                    WHERE approval_id = %s
                    """,
                    (approved, decided.model_dump_json(), approval_id),
                )
        return decided.model_copy(deep=True)

    def list_pending(self) -> list[ApprovalRecord]:
        self._ensure_schema()
        with self._factory.connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT payload::text FROM approvals WHERE approved IS NULL ORDER BY id ASC"
                )
                return [ApprovalRecord.model_validate_json(row[0]) for row in cur.fetchall()]

    def _ensure_schema(self) -> None:
        if self._initialized:
            return
        with self._factory.connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    CREATE TABLE IF NOT EXISTS approvals (
                        id BIGSERIAL PRIMARY KEY,
                        approval_id TEXT UNIQUE NOT NULL,
                        thread_id TEXT NOT NULL,
                        tool_name TEXT NOT NULL,
                        approved BOOLEAN,
                        payload JSONB NOT NULL,
                        created_at TIMESTAMPTZ DEFAULT now(),
                        decided_at TIMESTAMPTZ
                    )
                    """
                )
                cur.execute(
                    "CREATE INDEX IF NOT EXISTS idx_approvals_thread_id ON approvals(thread_id)"
                )
        self._initialized = True
