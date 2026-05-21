from agent_workflow.tools.idempotency import InMemoryIdempotencyStore, build_idempotency_key
from agent_workflow.tools.schemas import FunctionToolSpec, ToolCallResult


def test_build_idempotency_key_from_declared_fields() -> None:
    spec = FunctionToolSpec(
        name="save_feedback_draft",
        description="Save draft.",
        idempotency_key_source="submission_id+draft_revision",
        parameters={
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "submission_id": {"type": "string"},
                "draft_revision": {"type": "string"},
            },
        },
    )
    key = build_idempotency_key(
        spec,
        {"submission_id": "submission-1", "draft_revision": "r1"},
    )
    assert key == "save_feedback_draft:submission_id=submission-1|draft_revision=r1"


def test_in_memory_idempotency_store_returns_copy() -> None:
    store = InMemoryIdempotencyStore()
    result = ToolCallResult(tool_name="tool", accepted=True, output={"ok": True})
    store.record("key", result)
    cached = store.get("key")
    assert cached == result
    assert cached is not result
