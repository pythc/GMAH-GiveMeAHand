from agent_workflow.memory.models import MemoryKind, MemoryRecord, SessionSummary


def test_memory_record_requires_source_for_long_term_memory() -> None:
    record = MemoryRecord(
        id="mem-1",
        kind=MemoryKind.SEMANTIC,
        content="AGENTS.md is authoritative.",
        source="human-confirmed",
        scope="project:agent-workflow",
    )
    assert record.confidence == 1.0
    assert record.sensitive is False


def test_session_summary_defaults() -> None:
    summary = SessionSummary(thread_id="thread-1")
    assert summary.open_tasks == []
    assert summary.tool_side_effects == []
