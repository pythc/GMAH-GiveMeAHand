"""Tests for enhanced local MCP server tools, resources, and prompts."""

from __future__ import annotations

from pathlib import Path
from typing import Any, cast

import pytest
from fastapi.testclient import TestClient

from agent_workflow.mcp.local_server import (
    _resolve_sandboxed,
    create_app,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _rpc(client: TestClient, method: str, params: dict[str, object]) -> dict[str, Any]:
    response = client.post(
        "/mcp",
        json={"jsonrpc": "2.0", "id": "test-1", "method": method, "params": params},
    )
    assert response.status_code == 200
    return cast(dict[str, Any], response.json())


def _call_tool(
    client: TestClient, name: str, arguments: dict[str, object] | None = None
) -> dict[str, Any]:
    return _rpc(client, "tools/call", {"name": name, "arguments": arguments or {}})


@pytest.fixture()
def workspace(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Create a temporary workspace and patch WORKSPACE_ROOT."""
    # Create sample files
    (tmp_path / "hello.txt").write_text("line1\nline2\nline3\n")
    (tmp_path / "sub").mkdir()
    (tmp_path / "sub" / "nested.py").write_text("import os\nprint('hello')\n")
    (tmp_path / "data.csv").write_text("a,b,c\n1,2,3\n4,5,6\n")

    monkeypatch.setattr("agent_workflow.mcp.local_server.WORKSPACE_ROOT", tmp_path)
    return tmp_path


@pytest.fixture()
def client(workspace: Path) -> TestClient:
    """Create a test client with patched workspace."""
    return TestClient(create_app())


# ---------------------------------------------------------------------------
# Sandbox / path traversal tests
# ---------------------------------------------------------------------------


class TestSandbox:
    """Tests for sandbox path resolution and traversal prevention."""

    def test_resolve_relative_path(self, workspace: Path) -> None:
        resolved = _resolve_sandboxed("hello.txt")
        assert resolved == workspace / "hello.txt"

    def test_resolve_subdirectory(self, workspace: Path) -> None:
        resolved = _resolve_sandboxed("sub/nested.py")
        assert resolved == workspace / "sub" / "nested.py"

    def test_reject_double_dot_traversal(self, workspace: Path) -> None:
        with pytest.raises(ValueError, match="path traversal"):
            _resolve_sandboxed("../etc/passwd")

    def test_reject_hidden_traversal(self, workspace: Path) -> None:
        with pytest.raises(ValueError, match="path traversal"):
            _resolve_sandboxed("sub/../../etc/passwd")

    def test_reject_absolute_path_outside(
        self, workspace: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # Absolute path that escapes workspace
        with pytest.raises(ValueError, match="path traversal"):
            _resolve_sandboxed("foo/../../outside")

    def test_path_traversal_via_tool(self, client: TestClient) -> None:
        result = _call_tool(client, "read_file", {"path": "../etc/passwd"})
        assert "error" in result
        assert "path traversal" in result["error"]["message"]

    def test_list_directory_traversal(self, client: TestClient) -> None:
        result = _call_tool(client, "list_directory", {"path": "../../"})
        assert "error" in result
        assert "path traversal" in result["error"]["message"]

    def test_file_info_traversal(self, client: TestClient) -> None:
        result = _call_tool(client, "file_info", {"path": "../../../etc/passwd"})
        assert "error" in result
        assert "path traversal" in result["error"]["message"]

    def test_search_files_traversal(self, client: TestClient) -> None:
        result = _call_tool(client, "search_files", {"pattern": "*.py", "path": "../../"})
        assert "error" in result
        assert "path traversal" in result["error"]["message"]

    def test_grep_content_traversal(self, client: TestClient) -> None:
        result = _call_tool(client, "grep_content", {"pattern": "secret", "path": "../.."})
        assert "error" in result
        assert "path traversal" in result["error"]["message"]


# ---------------------------------------------------------------------------
# File system tool tests
# ---------------------------------------------------------------------------


class TestListDirectory:
    """Tests for list_directory tool."""

    def test_list_root(self, client: TestClient, workspace: Path) -> None:
        result = _call_tool(client, "list_directory", {"path": "."})
        payload = result["result"]["structuredContent"]
        names = {e["name"] for e in payload["entries"]}
        assert "hello.txt" in names
        assert "sub" in names
        assert "data.csv" in names

    def test_list_subdirectory(self, client: TestClient) -> None:
        result = _call_tool(client, "list_directory", {"path": "sub"})
        payload = result["result"]["structuredContent"]
        assert payload["entries"][0]["name"] == "nested.py"
        assert payload["entries"][0]["type"] == "file"

    def test_list_nonexistent(self, client: TestClient) -> None:
        result = _call_tool(client, "list_directory", {"path": "nonexistent"})
        assert "error" in result

    def test_entry_types(self, client: TestClient, workspace: Path) -> None:
        result = _call_tool(client, "list_directory", {"path": "."})
        payload = result["result"]["structuredContent"]
        types_by_name = {e["name"]: e["type"] for e in payload["entries"]}
        assert types_by_name["sub"] == "directory"
        assert types_by_name["hello.txt"] == "file"


class TestReadFile:
    """Tests for read_file tool."""

    def test_read_full_file(self, client: TestClient) -> None:
        result = _call_tool(client, "read_file", {"path": "hello.txt"})
        payload = result["result"]["structuredContent"]
        assert "line1" in payload["content"]
        assert "line2" in payload["content"]
        assert payload["total_lines"] == 3  # splitlines ignores trailing newline

    def test_read_with_offset(self, client: TestClient) -> None:
        result = _call_tool(client, "read_file", {"path": "hello.txt", "offset": 1})
        payload = result["result"]["structuredContent"]
        assert payload["content"].startswith("line2")

    def test_read_with_limit(self, client: TestClient) -> None:
        result = _call_tool(client, "read_file", {"path": "hello.txt", "offset": 0, "limit": 1})
        payload = result["result"]["structuredContent"]
        assert payload["content"] == "line1"

    def test_read_nonexistent(self, client: TestClient) -> None:
        result = _call_tool(client, "read_file", {"path": "nonexistent.txt"})
        assert "error" in result

    def test_read_directory_fails(self, client: TestClient) -> None:
        result = _call_tool(client, "read_file", {"path": "sub"})
        assert "error" in result

    def test_max_read_lines_enforced(
        self, client: TestClient, workspace: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Limit parameter is capped by MAX_READ_LINES."""
        monkeypatch.setattr("agent_workflow.mcp.local_server.MAX_READ_LINES", 2)
        result = _call_tool(client, "read_file", {"path": "hello.txt", "limit": 9999})
        payload = result["result"]["structuredContent"]
        # Should be capped to 2 lines
        assert payload["limit"] == 2


class TestFileInfo:
    """Tests for file_info tool."""

    def test_file_info(self, client: TestClient) -> None:
        result = _call_tool(client, "file_info", {"path": "hello.txt"})
        payload = result["result"]["structuredContent"]
        assert payload["type"] == "file"
        assert payload["size"] > 0
        assert "modified_time" in payload
        assert payload["is_symlink"] is False

    def test_directory_info(self, client: TestClient) -> None:
        result = _call_tool(client, "file_info", {"path": "sub"})
        payload = result["result"]["structuredContent"]
        assert payload["type"] == "directory"

    def test_nonexistent_info(self, client: TestClient) -> None:
        result = _call_tool(client, "file_info", {"path": "missing.txt"})
        assert "error" in result


# ---------------------------------------------------------------------------
# System tool tests
# ---------------------------------------------------------------------------


class TestSystemInfo:
    """Tests for system_info tool."""

    def test_system_info_fields(self, client: TestClient) -> None:
        result = _call_tool(client, "system_info")
        payload = result["result"]["structuredContent"]
        assert "python_version" in payload
        assert "platform" in payload
        assert "architecture" in payload
        assert "hostname" in payload
        assert "pid" in payload
        assert "memory" in payload
        assert "workspace_root" in payload


class TestCurrentTime:
    """Tests for current_time tool."""

    def test_utc_time(self, client: TestClient) -> None:
        result = _call_tool(client, "current_time", {"timezone": "UTC"})
        payload = result["result"]["structuredContent"]
        assert payload["timezone"] == "UTC"
        assert "iso" in payload
        assert "unix_timestamp" in payload

    def test_offset_timezone(self, client: TestClient) -> None:
        result = _call_tool(client, "current_time", {"timezone": "+08:00"})
        payload = result["result"]["structuredContent"]
        assert "+08:00" in payload["iso"]

    def test_negative_offset(self, client: TestClient) -> None:
        result = _call_tool(client, "current_time", {"timezone": "-05:00"})
        payload = result["result"]["structuredContent"]
        assert "-05:00" in payload["iso"]

    def test_invalid_timezone(self, client: TestClient) -> None:
        result = _call_tool(client, "current_time", {"timezone": "invalid"})
        assert "error" in result

    def test_default_timezone(self, client: TestClient) -> None:
        result = _call_tool(client, "current_time", {})
        payload = result["result"]["structuredContent"]
        assert payload["timezone"] == "UTC"


# ---------------------------------------------------------------------------
# Search tool tests
# ---------------------------------------------------------------------------


class TestSearchFiles:
    """Tests for search_files tool."""

    def test_search_py_files(self, client: TestClient) -> None:
        result = _call_tool(client, "search_files", {"pattern": "*.py"})
        payload = result["result"]["structuredContent"]
        matches = payload["matches"]
        assert any("nested.py" in m for m in matches)

    def test_search_txt_files(self, client: TestClient) -> None:
        result = _call_tool(client, "search_files", {"pattern": "*.txt"})
        payload = result["result"]["structuredContent"]
        assert any("hello.txt" in m for m in payload["matches"])

    def test_search_no_results(self, client: TestClient) -> None:
        result = _call_tool(client, "search_files", {"pattern": "*.xyz"})
        payload = result["result"]["structuredContent"]
        assert payload["matches"] == []

    def test_search_in_subdirectory(self, client: TestClient) -> None:
        result = _call_tool(client, "search_files", {"pattern": "*.py", "path": "sub"})
        payload = result["result"]["structuredContent"]
        assert len(payload["matches"]) == 1


class TestGrepContent:
    """Tests for grep_content tool."""

    def test_grep_simple_text(self, client: TestClient) -> None:
        result = _call_tool(client, "grep_content", {"pattern": "line2"})
        payload = result["result"]["structuredContent"]
        assert len(payload["results"]) > 0
        assert payload["results"][0]["content"] == "line2"

    def test_grep_regex(self, client: TestClient) -> None:
        result = _call_tool(client, "grep_content", {"pattern": r"line\d"})
        payload = result["result"]["structuredContent"]
        assert len(payload["results"]) >= 3

    def test_grep_in_specific_file(self, client: TestClient) -> None:
        result = _call_tool(client, "grep_content", {"pattern": "import", "path": "sub/nested.py"})
        payload = result["result"]["structuredContent"]
        assert len(payload["results"]) == 1
        assert payload["results"][0]["line"] == 1

    def test_grep_max_results(self, client: TestClient) -> None:
        result = _call_tool(client, "grep_content", {"pattern": ".", "max_results": 2})
        payload = result["result"]["structuredContent"]
        assert len(payload["results"]) <= 2

    def test_grep_invalid_regex(self, client: TestClient) -> None:
        result = _call_tool(client, "grep_content", {"pattern": "[invalid"})
        assert "error" in result

    def test_grep_no_results(self, client: TestClient) -> None:
        result = _call_tool(client, "grep_content", {"pattern": "ZZZZNOTFOUND"})
        payload = result["result"]["structuredContent"]
        assert payload["results"] == []


# ---------------------------------------------------------------------------
# Math tool tests
# ---------------------------------------------------------------------------


class TestCalculate:
    """Tests for calculate tool."""

    def test_basic_arithmetic(self, client: TestClient) -> None:
        result = _call_tool(client, "calculate", {"expression": "2 + 3 * 4"})
        payload = result["result"]["structuredContent"]
        assert payload["result"] == 14

    def test_division(self, client: TestClient) -> None:
        result = _call_tool(client, "calculate", {"expression": "10 / 3"})
        payload = result["result"]["structuredContent"]
        assert abs(payload["result"] - 3.333333) < 0.001

    def test_sqrt(self, client: TestClient) -> None:
        result = _call_tool(client, "calculate", {"expression": "sqrt(16)"})
        payload = result["result"]["structuredContent"]
        assert payload["result"] == 4.0

    def test_trig(self, client: TestClient) -> None:
        result = _call_tool(client, "calculate", {"expression": "sin(pi/2)"})
        payload = result["result"]["structuredContent"]
        assert abs(payload["result"] - 1.0) < 1e-10

    def test_constants(self, client: TestClient) -> None:
        result = _call_tool(client, "calculate", {"expression": "pi"})
        payload = result["result"]["structuredContent"]
        assert abs(payload["result"] - 3.14159) < 0.001

    def test_power(self, client: TestClient) -> None:
        result = _call_tool(client, "calculate", {"expression": "2 ** 10"})
        payload = result["result"]["structuredContent"]
        assert payload["result"] == 1024

    def test_disallowed_import(self, client: TestClient) -> None:
        result = _call_tool(client, "calculate", {"expression": "__import__('os')"})
        assert "error" in result

    def test_disallowed_builtin(self, client: TestClient) -> None:
        result = _call_tool(client, "calculate", {"expression": "eval('1+1')"})
        assert "error" in result

    def test_disallowed_function(self, client: TestClient) -> None:
        result = _call_tool(client, "calculate", {"expression": "open('/etc/passwd')"})
        assert "error" in result


# ---------------------------------------------------------------------------
# Resources tests
# ---------------------------------------------------------------------------


class TestResources:
    """Tests for MCP resources."""

    def test_list_resources_includes_new(self, client: TestClient) -> None:
        result = _rpc(client, "resources/list", {})
        resources = result["result"]["resources"]
        uris = {r["uri"] for r in resources}
        assert "system://info" in uris
        assert "workspace://files" in uris

    def test_read_system_info_resource(self, client: TestClient) -> None:
        result = _rpc(client, "resources/read", {"uri": "system://info"})
        contents = result["result"]["contents"]
        assert len(contents) == 1
        assert contents[0]["uri"] == "system://info"
        assert "python_version" in contents[0]["text"]

    def test_read_workspace_files_resource(self, client: TestClient) -> None:
        result = _rpc(client, "resources/read", {"uri": "workspace://files"})
        contents = result["result"]["contents"]
        assert len(contents) == 1
        assert contents[0]["uri"] == "workspace://files"
        assert "entries" in contents[0]["text"]

    def test_read_unknown_resource(self, client: TestClient) -> None:
        result = _rpc(client, "resources/read", {"uri": "unknown://foo"})
        assert "error" in result


# ---------------------------------------------------------------------------
# Prompts tests
# ---------------------------------------------------------------------------


class TestPrompts:
    """Tests for MCP prompts."""

    def test_list_prompts_includes_new(self, client: TestClient) -> None:
        result = _rpc(client, "prompts/list", {})
        prompts = result["result"]["prompts"]
        names = {p["name"] for p in prompts}
        assert "code_review" in names
        assert "summarize" in names
        assert "grading_review" in names

    def test_get_code_review_prompt(self, client: TestClient) -> None:
        result = _rpc(
            client,
            "prompts/get",
            {
                "name": "code_review",
                "arguments": {"code": "x = 1", "language": "python"},
            },
        )
        prompt = result["result"]
        assert prompt["description"] == "对代码片段进行结构化审查。"
        assert len(prompt["messages"]) == 1
        assert "python" in prompt["messages"][0]["content"]["text"]
        assert "x = 1" in prompt["messages"][0]["content"]["text"]

    def test_get_summarize_prompt(self, client: TestClient) -> None:
        result = _rpc(
            client,
            "prompts/get",
            {
                "name": "summarize",
                "arguments": {"content": "Some long document.", "max_length": "100"},
            },
        )
        prompt = result["result"]
        assert prompt["description"] == "生成文档的结构化摘要。"
        assert "100" in prompt["messages"][0]["content"]["text"]
        assert "Some long document." in prompt["messages"][0]["content"]["text"]

    def test_get_unknown_prompt(self, client: TestClient) -> None:
        result = _rpc(client, "prompts/get", {"name": "nonexistent"})
        assert "error" in result


# ---------------------------------------------------------------------------
# Tools listing test
# ---------------------------------------------------------------------------


class TestToolsList:
    """Tests for tools/list endpoint."""

    def test_all_tools_listed(self, client: TestClient) -> None:
        result = _rpc(client, "tools/list", {})
        tools = result["result"]["tools"]
        names = {t["name"] for t in tools}
        expected = {
            "fetch_submission",
            "save_feedback_draft",
            "publish_grade",
            "list_directory",
            "read_file",
            "file_info",
            "system_info",
            "current_time",
            "search_files",
            "grep_content",
            "calculate",
        }
        assert expected.issubset(names)

    def test_all_tools_have_input_schema(self, client: TestClient) -> None:
        result = _rpc(client, "tools/list", {})
        tools = result["result"]["tools"]
        for tool in tools:
            assert "inputSchema" in tool, f"tool {tool['name']} missing inputSchema"
            schema = tool["inputSchema"]
            assert schema["type"] == "object"
            assert "properties" in schema
