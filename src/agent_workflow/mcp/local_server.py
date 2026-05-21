"""Local JSON-RPC MCP-compatible server for development and integration tests.

Provides grading tools, file system tools, system tools, search tools, and math tools.
All file operations are sandboxed within WORKSPACE_ROOT.
"""

from __future__ import annotations

import fnmatch
import math
import os
import platform
import re
import sys
import time
from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from fastapi import FastAPI
from pydantic import BaseModel, Field

from agent_workflow import __version__
from agent_workflow.integrations.grading.adapter import (
    GradingAdapterError,
    LocalGradingSystemAdapter,
)

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

WORKSPACE_ROOT: Path = Path(os.environ.get("WORKSPACE_ROOT", ".")).resolve()
MAX_READ_LINES: int = int(os.environ.get("MCP_MAX_READ_LINES", "500"))

# ---------------------------------------------------------------------------
# Sandbox helpers
# ---------------------------------------------------------------------------


def _resolve_sandboxed(path_str: str) -> Path:
    """Resolve a path ensuring it stays within WORKSPACE_ROOT.

    Raises ValueError on path traversal attempts.
    """
    # Reject obvious traversal patterns before resolution
    if ".." in path_str.replace("\\", "/").split("/"):
        raise ValueError("path traversal is not allowed")

    resolved = (WORKSPACE_ROOT / path_str).resolve()
    # Use os.sep suffix to prevent /workspace matching /workspace-other
    if resolved != WORKSPACE_ROOT and not str(resolved).startswith(str(WORKSPACE_ROOT) + os.sep):
        raise ValueError("path traversal is not allowed")
    return resolved


# ---------------------------------------------------------------------------
# JSON-RPC model
# ---------------------------------------------------------------------------


class JsonRpcRequest(BaseModel):
    jsonrpc: str = "2.0"
    id: str | int | None = None
    method: str
    params: dict[str, Any] = Field(default_factory=dict)


# ---------------------------------------------------------------------------
# App factory
# ---------------------------------------------------------------------------


def create_app() -> FastAPI:
    """Create a local MCP-compatible JSON-RPC server."""

    app = FastAPI(
        title="Agent Workflow Local MCP Server",
        version=__version__,
        description=(
            "Local MCP-compatible server exposing grading tools, file system tools, "
            "system utilities, search, and math capabilities."
        ),
    )
    adapter = LocalGradingSystemAdapter()

    @app.get("/healthz", tags=["system"])
    def healthz() -> dict[str, str]:
        return {"status": "ok", "version": __version__}

    @app.post("/mcp", tags=["mcp"])
    def mcp(request: JsonRpcRequest) -> dict[str, Any]:
        try:
            result = _dispatch(request.method, request.params, adapter)
            return {"jsonrpc": "2.0", "id": request.id, "result": result}
        except Exception as exc:  # noqa: BLE001 - JSON-RPC returns structured errors.
            return {
                "jsonrpc": "2.0",
                "id": request.id,
                "error": {"code": -32000, "message": str(exc)},
            }

    return app


# ---------------------------------------------------------------------------
# Dispatch
# ---------------------------------------------------------------------------


def _dispatch(
    method: str,
    params: dict[str, Any],
    adapter: LocalGradingSystemAdapter,
) -> dict[str, Any]:
    if method == "tools/list":
        return {"tools": _tools()}
    if method == "resources/list":
        return {"resources": _resources()}
    if method == "prompts/list":
        return {"prompts": _prompts()}
    if method == "tools/call":
        return _call_tool(params, adapter)
    if method == "resources/read":
        return _read_resource(params, adapter)
    if method == "prompts/get":
        return _get_prompt(params)
    raise ValueError(f"unsupported MCP method: {method}")


# ---------------------------------------------------------------------------
# Tools definition
# ---------------------------------------------------------------------------


def _tools() -> list[dict[str, Any]]:
    return [
        # --- Grading tools ---
        {
            "name": "fetch_submission",
            "description": "读取学生提交内容",
            "inputSchema": {
                "type": "object",
                "additionalProperties": False,
                "properties": {"submission_id": {"type": "string", "minLength": 1}},
                "required": ["submission_id"],
            },
        },
        {
            "name": "save_feedback_draft",
            "description": "保存评分反馈草稿，不正式发布成绩",
            "inputSchema": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "submission_id": {"type": "string", "minLength": 1},
                    "draft_revision": {"type": "string", "minLength": 1},
                    "feedback_markdown": {"type": "string", "minLength": 1},
                },
                "required": ["submission_id", "draft_revision", "feedback_markdown"],
            },
        },
        {
            "name": "publish_grade",
            "description": "将评分结果回写到批改系统并向学生发布，本地服务仅做 mock",
            "inputSchema": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "submission_id": {"type": "string", "minLength": 1},
                    "rubric_version": {"type": "string", "minLength": 1},
                    "score": {"type": "number", "minimum": 0},
                    "feedback_markdown": {"type": "string", "minLength": 1},
                },
                "required": [
                    "submission_id",
                    "rubric_version",
                    "score",
                    "feedback_markdown",
                ],
            },
        },
        # --- File system tools ---
        {
            "name": "list_directory",
            "description": "列出目录内容，返回文件名、类型和大小",
            "inputSchema": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "相对于工作区根目录的路径，默认为 '.'",
                        "default": ".",
                    }
                },
                "required": [],
            },
        },
        {
            "name": "read_file",
            "description": "读取文件内容，支持 offset 和 limit 参数",
            "inputSchema": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "相对于工作区根目录的文件路径",
                    },
                    "offset": {
                        "type": "integer",
                        "description": "起始行号（从 0 开始），默认为 0",
                        "minimum": 0,
                        "default": 0,
                    },
                    "limit": {
                        "type": "integer",
                        "description": f"最多读取行数，默认和上限为 {MAX_READ_LINES}",
                        "minimum": 1,
                        "default": MAX_READ_LINES,
                    },
                },
                "required": ["path"],
            },
        },
        {
            "name": "file_info",
            "description": "获取文件元信息（大小、修改时间、类型）",
            "inputSchema": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "相对于工作区根目录的文件路径",
                    }
                },
                "required": ["path"],
            },
        },
        # --- System tools ---
        {
            "name": "system_info",
            "description": "返回系统信息（Python版本、平台、内存使用等）",
            "inputSchema": {
                "type": "object",
                "additionalProperties": False,
                "properties": {},
                "required": [],
            },
        },
        {
            "name": "current_time",
            "description": "返回当前时间（支持多时区）",
            "inputSchema": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "timezone": {
                        "type": "string",
                        "description": ("时区偏移，如 '+08:00'、'-05:00' 或 'UTC'，默认 UTC"),
                        "default": "UTC",
                    }
                },
                "required": [],
            },
        },
        # --- Search tools ---
        {
            "name": "search_files",
            "description": "在目录中递归搜索匹配模式的文件名",
            "inputSchema": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "pattern": {
                        "type": "string",
                        "description": "文件名匹配模式（支持 glob 通配符，如 '*.py'）",
                    },
                    "path": {
                        "type": "string",
                        "description": "搜索起始目录，相对于工作区根目录，默认为 '.'",
                        "default": ".",
                    },
                },
                "required": ["pattern"],
            },
        },
        {
            "name": "grep_content",
            "description": "在文件中搜索文本内容（正则表达式）",
            "inputSchema": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "pattern": {
                        "type": "string",
                        "description": "搜索正则表达式",
                    },
                    "path": {
                        "type": "string",
                        "description": "搜索起始目录或文件路径，默认为 '.'",
                        "default": ".",
                    },
                    "max_results": {
                        "type": "integer",
                        "description": "最大结果数量，默认 50",
                        "minimum": 1,
                        "default": 50,
                    },
                },
                "required": ["pattern"],
            },
        },
        # --- Math tools ---
        {
            "name": "calculate",
            "description": "安全的数学表达式求值（支持基本运算和常用函数）",
            "inputSchema": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "expression": {
                        "type": "string",
                        "description": ("数学表达式，如 '2+3*4'、'sqrt(16)'、'sin(pi/2)'"),
                    }
                },
                "required": ["expression"],
            },
        },
    ]


# ---------------------------------------------------------------------------
# Resources definition
# ---------------------------------------------------------------------------


def _resources() -> list[dict[str, str]]:
    return [
        {
            "uri": "course",
            "name": "课程",
            "description": "本地示例课程",
            "mimeType": "application/json",
        },
        {
            "uri": "assignment",
            "name": "作业",
            "description": "本地示例作业",
            "mimeType": "application/json",
        },
        {
            "uri": "rubric",
            "name": "评分标准",
            "description": "本地示例 rubric",
            "mimeType": "application/json",
        },
        {
            "uri": "system://info",
            "name": "系统信息",
            "description": "当前系统运行时信息",
            "mimeType": "application/json",
        },
        {
            "uri": "workspace://files",
            "name": "工作区文件列表",
            "description": "工作区根目录文件列表",
            "mimeType": "application/json",
        },
    ]


# ---------------------------------------------------------------------------
# Prompts definition
# ---------------------------------------------------------------------------


def _prompts() -> list[dict[str, Any]]:
    return [
        {
            "name": "grading_review",
            "description": "根据 rubric 生成结构化批改反馈",
            "arguments": [
                {"name": "submission_id", "description": "学生提交 ID", "required": True},
                {"name": "rubric_version", "description": "Rubric 版本", "required": True},
            ],
        },
        {
            "name": "code_review",
            "description": "代码审查提示模板，用于对代码片段进行结构化审查",
            "arguments": [
                {
                    "name": "code",
                    "description": "需要审查的代码内容",
                    "required": True,
                },
                {
                    "name": "language",
                    "description": "编程语言（如 python, javascript）",
                    "required": False,
                },
            ],
        },
        {
            "name": "summarize",
            "description": "文档摘要提示模板，用于生成文档的结构化摘要",
            "arguments": [
                {
                    "name": "content",
                    "description": "需要摘要的文档内容",
                    "required": True,
                },
                {
                    "name": "max_length",
                    "description": "摘要最大字数",
                    "required": False,
                },
            ],
        },
    ]


# ---------------------------------------------------------------------------
# Tool call dispatcher
# ---------------------------------------------------------------------------


def _call_tool(params: dict[str, Any], adapter: LocalGradingSystemAdapter) -> dict[str, Any]:
    name = _require_str(params, "name")
    arguments = params.get("arguments", {})
    if not isinstance(arguments, dict):
        raise ValueError("arguments must be an object")

    # Grading tools
    if name == "fetch_submission":
        payload = adapter.fetch_submission(_require_str(arguments, "submission_id")).model_dump(
            mode="json"
        )
    elif name == "save_feedback_draft":
        payload = adapter.save_feedback_draft(
            submission_id=_require_str(arguments, "submission_id"),
            draft_revision=_require_str(arguments, "draft_revision"),
            feedback_markdown=_require_str(arguments, "feedback_markdown"),
        ).model_dump(mode="json")
    elif name == "publish_grade":
        payload = adapter.publish_grade(
            submission_id=_require_str(arguments, "submission_id"),
            rubric_version=_require_str(arguments, "rubric_version"),
            score=_require_number(arguments, "score"),
            feedback_markdown=_require_str(arguments, "feedback_markdown"),
        ).model_dump(mode="json")
    # File system tools
    elif name == "list_directory":
        payload = _tool_list_directory(arguments)
    elif name == "read_file":
        payload = _tool_read_file(arguments)
    elif name == "file_info":
        payload = _tool_file_info(arguments)
    # System tools
    elif name == "system_info":
        payload = _tool_system_info()
    elif name == "current_time":
        payload = _tool_current_time(arguments)
    # Search tools
    elif name == "search_files":
        payload = _tool_search_files(arguments)
    elif name == "grep_content":
        payload = _tool_grep_content(arguments)
    # Math tools
    elif name == "calculate":
        payload = _tool_calculate(arguments)
    else:
        raise ValueError(f"unknown tool: {name}")

    return {
        "content": [{"type": "text", "text": str(payload)}],
        "structuredContent": payload,
    }


# ---------------------------------------------------------------------------
# Resource reader
# ---------------------------------------------------------------------------


def _read_resource(params: dict[str, Any], adapter: LocalGradingSystemAdapter) -> dict[str, Any]:
    uri = _require_str(params, "uri")
    try:
        if uri == "course":
            payload = {"course_id": "course-ml-101", "title": "智能体系统课程"}
        elif uri == "assignment":
            payload = adapter.fetch_assignment("assignment-1").model_dump(mode="json")
        elif uri == "rubric":
            payload = adapter.fetch_rubric("assignment-1", "v1").model_dump(mode="json")
        elif uri == "system://info":
            payload = _tool_system_info()
        elif uri == "workspace://files":
            payload = _tool_list_directory({"path": "."})
        else:
            raise ValueError(f"unknown resource: {uri}")
    except GradingAdapterError as exc:
        raise ValueError(str(exc)) from exc

    return {"contents": [{"uri": uri, "mimeType": "application/json", "text": str(payload)}]}


# ---------------------------------------------------------------------------
# Prompt getter
# ---------------------------------------------------------------------------


def _get_prompt(params: dict[str, Any]) -> dict[str, Any]:
    name = _require_str(params, "name")
    arguments = params.get("arguments", {})
    if not isinstance(arguments, dict):
        arguments = {}

    if name == "grading_review":
        return {
            "description": "根据 rubric 对提交内容进行结构化批改。",
            "messages": [
                {
                    "role": "user",
                    "content": {
                        "type": "text",
                        "text": (
                            "请读取 submission 和 rubric，输出优点、问题、分数建议和改进建议。"
                        ),
                    },
                }
            ],
        }

    if name == "code_review":
        code = arguments.get("code", "")
        language = arguments.get("language", "unknown")
        return {
            "description": "对代码片段进行结构化审查。",
            "messages": [
                {
                    "role": "user",
                    "content": {
                        "type": "text",
                        "text": (
                            f"请对以下 {language} 代码进行审查，"
                            "指出潜在问题、代码风格改进建议和性能优化建议：\n\n"
                            f"```{language}\n{code}\n```"
                        ),
                    },
                }
            ],
        }

    if name == "summarize":
        content = arguments.get("content", "")
        max_length = arguments.get("max_length", "200")
        return {
            "description": "生成文档的结构化摘要。",
            "messages": [
                {
                    "role": "user",
                    "content": {
                        "type": "text",
                        "text": (
                            f"请为以下内容生成不超过 {max_length} 字的摘要，"
                            "包含核心要点和关键结论：\n\n"
                            f"{content}"
                        ),
                    },
                }
            ],
        }

    raise ValueError(f"unknown prompt: {name}")


# ---------------------------------------------------------------------------
# File system tool implementations
# ---------------------------------------------------------------------------


def _tool_list_directory(arguments: dict[str, Any]) -> dict[str, Any]:
    """List directory entries with name, type, and size."""
    path_str: str = arguments.get("path", ".")
    resolved = _resolve_sandboxed(path_str)

    if not resolved.exists():
        raise ValueError(f"path does not exist: {path_str}")
    if not resolved.is_dir():
        raise ValueError(f"path is not a directory: {path_str}")

    entries: list[dict[str, Any]] = []
    for entry in sorted(resolved.iterdir(), key=lambda p: p.name):
        stat = entry.stat()
        entries.append(
            {
                "name": entry.name,
                "type": "directory" if entry.is_dir() else "file",
                "size": stat.st_size,
            }
        )

    return {"path": path_str, "entries": entries}


def _tool_read_file(arguments: dict[str, Any]) -> dict[str, Any]:
    """Read file content with offset/limit support."""
    path_str = _require_str(arguments, "path")
    offset: int = int(arguments.get("offset", 0))
    limit: int = min(int(arguments.get("limit", MAX_READ_LINES)), MAX_READ_LINES)

    resolved = _resolve_sandboxed(path_str)

    if not resolved.exists():
        raise ValueError(f"file does not exist: {path_str}")
    if not resolved.is_file():
        raise ValueError(f"path is not a file: {path_str}")

    lines = resolved.read_text(encoding="utf-8", errors="replace").splitlines()
    total_lines = len(lines)
    selected = lines[offset : offset + limit]

    return {
        "path": path_str,
        "total_lines": total_lines,
        "offset": offset,
        "limit": limit,
        "content": "\n".join(selected),
    }


def _tool_file_info(arguments: dict[str, Any]) -> dict[str, Any]:
    """Get file metadata."""
    path_str = _require_str(arguments, "path")
    resolved = _resolve_sandboxed(path_str)

    if not resolved.exists():
        raise ValueError(f"path does not exist: {path_str}")

    stat = resolved.stat()
    return {
        "path": path_str,
        "size": stat.st_size,
        "modified_time": datetime.fromtimestamp(stat.st_mtime, tz=UTC).isoformat(),
        "type": "directory" if resolved.is_dir() else "file",
        "is_symlink": resolved.is_symlink(),
    }


# ---------------------------------------------------------------------------
# System tool implementations
# ---------------------------------------------------------------------------


def _tool_system_info() -> dict[str, Any]:
    """Return system information."""
    try:
        import psutil

        mem = psutil.virtual_memory()
        memory_info = {
            "total_mb": round(mem.total / 1024 / 1024, 1),
            "available_mb": round(mem.available / 1024 / 1024, 1),
            "percent_used": mem.percent,
        }
    except ImportError:
        memory_info = {"note": "psutil not installed, memory info unavailable"}

    return {
        "python_version": sys.version,
        "platform": platform.platform(),
        "architecture": platform.machine(),
        "hostname": platform.node(),
        "pid": os.getpid(),
        "workspace_root": str(WORKSPACE_ROOT),
        "memory": memory_info,
    }


def _tool_current_time(arguments: dict[str, Any]) -> dict[str, Any]:
    """Return current time in specified timezone."""
    tz_str: str = arguments.get("timezone", "UTC")

    if tz_str.upper() == "UTC":
        tz = UTC
    else:
        # Parse offset like "+08:00" or "-05:00"
        match = re.match(r"^([+-])(\d{2}):(\d{2})$", tz_str)
        if not match:
            raise ValueError(f"invalid timezone format: {tz_str} (use 'UTC' or '+HH:MM'/'-HH:MM')")
        sign = 1 if match.group(1) == "+" else -1
        hours = int(match.group(2))
        minutes = int(match.group(3))
        tz = timezone(timedelta(hours=sign * hours, minutes=sign * minutes))

    now = datetime.now(tz=tz)
    return {
        "iso": now.isoformat(),
        "unix_timestamp": time.time(),
        "timezone": tz_str,
    }


# ---------------------------------------------------------------------------
# Search tool implementations
# ---------------------------------------------------------------------------


def _tool_search_files(arguments: dict[str, Any]) -> dict[str, Any]:
    """Recursively search for files matching a glob pattern."""
    pattern = _require_str(arguments, "pattern")
    path_str: str = arguments.get("path", ".")
    resolved = _resolve_sandboxed(path_str)

    if not resolved.exists():
        raise ValueError(f"path does not exist: {path_str}")
    if not resolved.is_dir():
        raise ValueError(f"path is not a directory: {path_str}")

    matches: list[str] = []
    max_matches = 200

    for root, _dirs, files in os.walk(resolved):
        for filename in files:
            if fnmatch.fnmatch(filename, pattern):
                full = Path(root) / filename
                # Ensure still within sandbox
                if str(full.resolve()).startswith(str(WORKSPACE_ROOT)):
                    rel = str(full.relative_to(WORKSPACE_ROOT))
                    matches.append(rel)
                    if len(matches) >= max_matches:
                        break
        if len(matches) >= max_matches:
            break

    return {"pattern": pattern, "base_path": path_str, "matches": matches}


def _tool_grep_content(arguments: dict[str, Any]) -> dict[str, Any]:
    """Search for text content in files using regex."""
    pattern = _require_str(arguments, "pattern")
    path_str: str = arguments.get("path", ".")
    max_results: int = int(arguments.get("max_results", 50))
    resolved = _resolve_sandboxed(path_str)

    if not resolved.exists():
        raise ValueError(f"path does not exist: {path_str}")

    try:
        regex = re.compile(pattern)
    except re.error as exc:
        raise ValueError(f"invalid regex pattern: {exc}") from exc

    results: list[dict[str, Any]] = []

    if resolved.is_file():
        files_to_search = [resolved]
    else:
        files_to_search = []
        for root, _dirs, filenames in os.walk(resolved):
            for fname in filenames:
                fp = Path(root) / fname
                if str(fp.resolve()).startswith(str(WORKSPACE_ROOT)):
                    files_to_search.append(fp)

    for fpath in files_to_search:
        if len(results) >= max_results:
            break
        try:
            lines = fpath.read_text(encoding="utf-8", errors="replace").splitlines()
        except (OSError, PermissionError):
            continue
        for line_no, line in enumerate(lines, start=1):
            if regex.search(line):
                rel = str(fpath.relative_to(WORKSPACE_ROOT))
                results.append(
                    {
                        "file": rel,
                        "line": line_no,
                        "content": line[:200],
                    }
                )
                if len(results) >= max_results:
                    break

    return {"pattern": pattern, "base_path": path_str, "results": results}


# ---------------------------------------------------------------------------
# Math tool implementation
# ---------------------------------------------------------------------------

# Allowed names for safe math evaluation
_MATH_ALLOWED_NAMES: dict[str, Any] = {
    "abs": abs,
    "round": round,
    "min": min,
    "max": max,
    "sum": sum,
    "int": int,
    "float": float,
    # math module functions
    "sqrt": math.sqrt,
    "sin": math.sin,
    "cos": math.cos,
    "tan": math.tan,
    "asin": math.asin,
    "acos": math.acos,
    "atan": math.atan,
    "atan2": math.atan2,
    "log": math.log,
    "log2": math.log2,
    "log10": math.log10,
    "exp": math.exp,
    "pow": math.pow,
    "ceil": math.ceil,
    "floor": math.floor,
    "factorial": math.factorial,
    "gcd": math.gcd,
    # Constants
    "pi": math.pi,
    "e": math.e,
    "inf": math.inf,
    "tau": math.tau,
}


def _tool_calculate(arguments: dict[str, Any]) -> dict[str, Any]:
    """Safely evaluate a math expression."""
    expression = _require_str(arguments, "expression")

    # Validate: only allow safe characters
    if re.search(r"[a-zA-Z_]\w*\s*\(", expression):
        # Check that all function calls are in allowed names
        for match in re.finditer(r"([a-zA-Z_]\w*)\s*\(", expression):
            func_name = match.group(1)
            if func_name not in _MATH_ALLOWED_NAMES:
                raise ValueError(f"function not allowed: {func_name}")

    # Block dangerous patterns
    if any(kw in expression for kw in ("import", "__", "eval", "exec", "open", "os.")):
        raise ValueError("expression contains disallowed keywords")

    try:
        result = eval(expression, {"__builtins__": {}}, _MATH_ALLOWED_NAMES)  # noqa: S307
    except Exception as exc:
        raise ValueError(f"evaluation error: {exc}") from exc

    return {"expression": expression, "result": result}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _require_str(payload: dict[str, Any], key: str) -> str:
    value = payload.get(key)
    if not isinstance(value, str) or not value:
        raise ValueError(f"{key} must be a non-empty string")
    return value


def _require_number(payload: dict[str, Any], key: str) -> float:
    value = payload.get(key)
    if not isinstance(value, int | float):
        raise ValueError(f"{key} must be a number")
    return float(value)
