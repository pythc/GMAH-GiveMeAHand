"""Agentic repository review using local read-only tools and an LLM."""

import base64
import ipaddress
import json
import os
import re
import subprocess
import tarfile
import tempfile
import urllib.parse
import zipfile
from collections import Counter
from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from agent_workflow.evaluation.history import ReviewHistoryStore
from agent_workflow.evaluation.models import ArtifactInput, ArtifactKind, ProjectEvaluationResult
from agent_workflow.evaluation.repository import RepositoryAnalysisError, normalize_github_url
from agent_workflow.llm.models import ChatCompletionRequest, ChatMessage
from agent_workflow.llm.openai_compatible import OpenAICompatibleChatClient

_DEFAULT_ROOT = Path("data/repository-agent-workspaces")
_SKIP_DIRS = {
    ".git",
    ".venv",
    "venv",
    "node_modules",
    "dist",
    "build",
    ".next",
    ".cache",
    "__pycache__",
    "target",
    ".idea",
    ".vscode",
}
_TEXT_SUFFIXES = {
    ".md",
    ".txt",
    ".rst",
    ".toml",
    ".json",
    ".yaml",
    ".yml",
    ".py",
    ".ts",
    ".tsx",
    ".js",
    ".jsx",
    ".go",
    ".java",
    ".rs",
    ".c",
    ".h",
    ".cpp",
    ".hpp",
    ".sh",
    ".sql",
}
_IMPORTANT_NAMES = {
    "readme.md",
    "readme.rst",
    "readme.txt",
    "pyproject.toml",
    "package.json",
    "requirements.txt",
    "go.mod",
    "pom.xml",
    "cargo.toml",
    "dockerfile",
    "docker-compose.yml",
    "compose.yml",
    "makefile",
}

class RepositoryToolObservation(BaseModel):
    tool: str
    input: dict[str, Any] = Field(default_factory=dict)
    output: str


class RepositoryFileEvidence(BaseModel):
    path: str
    chars: int
    content: str


RepositoryProgressCallback = Callable[[str], None]
RepositoryToolLogCallback = Callable[[str, dict[str, Any], dict[str, Any]], None]
RepositoryRagCallback = Callable[[str], list[dict[str, Any]]]


class AgenticRepositoryReview(BaseModel):
    source_url: str
    final_review: str
    inspected_files: list[str]
    observations: list[RepositoryToolObservation]
    file_evidence: list[RepositoryFileEvidence]

    def to_artifact(self) -> ArtifactInput:
        return ArtifactInput(
            artifact_id="agentic-github-repository",
            kind=ArtifactKind.CODE_REPOSITORY,
            title="AI 自主工具审查的 GitHub 代码仓库",
            uri=self.source_url,
            repository_summary=self.to_evidence_text(),
            metadata={
                "inspected_files": self.inspected_files,
                "tool_observations": [item.model_dump() for item in self.observations],
            },
        )

    def to_evidence_text(self) -> str:
        observations = "\n".join(_format_observation_cn(item) for item in self.observations)
        files = "\n\n".join(
            f"--- {item.path}（{item.chars} 个字符）---\n{item.content}"
            for item in self.file_evidence
        )
        return (
            f"仓库地址：{self.source_url}\n"
            f"AI 工具调用观察：\n{observations}\n\n"
            f"AI 已逐个读取的文件证据：\n{files}"
        )


class AgenticRepositoryReviewer:
    """Run a model-driven tool loop for repository review."""

    def __init__(
        self,
        *,
        root_dir: Path = _DEFAULT_ROOT,
        clone_timeout_seconds: int = 90,
        max_listed_files: int = 1200,
        max_inspected_files: int = 80,
        max_file_chars: int = 12_000,
        max_total_chars: int = 180_000,
        max_tool_calls: int = 40,
        selection_rounds: int = 2,
        history_store: ReviewHistoryStore | None = None,
    ) -> None:
        self.root_dir = root_dir
        self.clone_timeout_seconds = clone_timeout_seconds
        self.max_listed_files = max_listed_files
        self.max_inspected_files = max_inspected_files
        self.max_file_chars = max_file_chars
        self.max_total_chars = max_total_chars
        self.max_tool_calls = max_tool_calls
        self.selection_rounds = selection_rounds
        self.history_store = history_store or ReviewHistoryStore()

    def review_url(
        self,
        url: str,
        *,
        topic_title: str,
        topic_goal: str,
        chat_client: OpenAICompatibleChatClient | None,
        agent_system_prompt: str,
        rule_evaluation: ProjectEvaluationResult | None = None,
        progress_callback: RepositoryProgressCallback | None = None,
        tool_log_callback: RepositoryToolLogCallback | None = None,
        rag_callback: RepositoryRagCallback | None = None,
        progress_level: str = "normal",
    ) -> AgenticRepositoryReview:
        clone_url, repo_key = normalize_github_url(url)
        self.root_dir.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix=f"{repo_key}-", dir=self.root_dir) as workspace:
            repo_path = Path(workspace) / "repo"
            observations: list[RepositoryToolObservation] = []
            evidence: list[RepositoryFileEvidence] = []
            files: list[str] = []
            history_checked = False
            history_action_taken = False
            # Track required tool calls for workflow enforcement
            tools_called: set[str] = set()
            # Mutable counter: limit template rejections to prevent infinite loop
            rejection_state = {"final_answer_rejections": 0}
            if not _can_call_model(chat_client):
                return self._fallback_tool_review(
                    clone_url=clone_url,
                    repo_path=repo_path,
                    observations=observations,
                    evidence=evidence,
                    rule_evaluation=rule_evaluation,
                )
            assert chat_client is not None
            final_review = ""
            messages = [
                ChatMessage(role="system", content=agent_system_prompt),
                ChatMessage(
                    role="user",
                    content=_tool_loop_task_message(
                        url=clone_url,
                        topic_title=topic_title,
                        topic_goal=topic_goal,
                        rule_evaluation=rule_evaluation,
                        progress_instruction=_progress_instruction(progress_level),
                    ),
                ),
            ]
            for _ in range(self.max_tool_calls):
                result = chat_client.chat(
                    ChatCompletionRequest(
                        messages=messages,
                        temperature=0.2,
                        max_tokens=8000,
                    )
                )
                tool_call = _extract_json_object(result.content)
                tool = tool_call.get("tool")
                arguments = tool_call.get("arguments", {})
                if not isinstance(tool, str) or not isinstance(arguments, dict):
                    messages.append(ChatMessage(role="assistant", content=result.content))
                    messages.append(ChatMessage(role="user", content=_invalid_tool_observation()))
                    continue
                observation = self._execute_tool(
                    tool=tool,
                    arguments=arguments,
                    clone_url=clone_url,
                    repo_path=repo_path,
                    observations=observations,
                    evidence=evidence,
                    files=files,
                    progress_callback=progress_callback,
                    tool_log_callback=tool_log_callback,
                    rag_callback=rag_callback,
                    history_checked=history_checked,
                    history_action_taken=history_action_taken,
                    topic_title=topic_title,
                    chat_client=chat_client,
                    messages=messages,
                    tools_called=tools_called,
                    rejection_state=rejection_state,
                )
                if tool == "get_review_history" and observation.get("ok"):
                    history_checked = True
                if tool == "update_review_history" and observation.get("ok"):
                    history_action_taken = True
                if observation.get("ok"):
                    tools_called.add(tool)
                messages.append(ChatMessage(role="assistant", content=result.content))
                messages.append(
                    ChatMessage(role="user", content=_tool_observation_message(observation))
                )
                if tool == "final_answer" and observation["ok"]:
                    final_review = str(arguments.get("message") or "").strip()
                    break
            if not final_review:
                final_review = _fallback_review(clone_url, evidence, rule_evaluation)
            self._append_cleanup_observation(observations)
            return AgenticRepositoryReview(
                source_url=clone_url,
                final_review=final_review[:12000],
                inspected_files=[item.path for item in evidence],
                observations=observations,
                file_evidence=evidence,
            )

    def _fallback_tool_review(
        self,
        *,
        clone_url: str,
        repo_path: Path,
        observations: list[RepositoryToolObservation],
        evidence: list[RepositoryFileEvidence],
        rule_evaluation: ProjectEvaluationResult | None,
    ) -> AgenticRepositoryReview:
        self._clone(clone_url, repo_path, observations)
        files = _safe_files(repo_path, max_files=self.max_listed_files)
        observations.append(
            RepositoryToolObservation(
                tool="list_files",
                input={"max_files": self.max_listed_files},
                output=f"{len(files)} files listed",
            )
        )
        selected = _initial_file_selection(files, self.max_inspected_files)
        evidence.extend(self._read_selected_files(repo_path, selected, observations))
        final_review = _fallback_review(clone_url, evidence, rule_evaluation)
        self._append_cleanup_observation(observations)
        return AgenticRepositoryReview(
            source_url=clone_url,
            final_review=final_review,
            inspected_files=[item.path for item in evidence],
            observations=observations,
            file_evidence=evidence,
        )

    def _execute_tool(
        self,
        *,
        tool: str,
        arguments: dict[str, Any],
        clone_url: str,
        repo_path: Path,
        observations: list[RepositoryToolObservation],
        evidence: list[RepositoryFileEvidence],
        files: list[str],
        progress_callback: RepositoryProgressCallback | None,
        tool_log_callback: RepositoryToolLogCallback | None,
        rag_callback: RepositoryRagCallback | None,
        history_checked: bool,
        history_action_taken: bool,
        topic_title: str,
        chat_client: OpenAICompatibleChatClient | None = None,
        messages: list[ChatMessage] | None = None,
        tools_called: set[str] | None = None,
        rejection_state: dict[str, int] | None = None,
    ) -> dict[str, Any]:
        try:
            if tool == "clone_repository":
                result = self._tool_clone_repository(arguments, clone_url, repo_path, observations)
            elif tool == "list_files":
                result = self._tool_list_files(arguments, repo_path, observations, files)
            elif tool == "read_file":
                result = self._tool_read_file(arguments, repo_path, observations, evidence)
            elif tool == "view_document_page":
                result = self._tool_view_document_page(
                    arguments, repo_path, observations, chat_client, messages
                )
            elif tool == "inspect_archive":
                result = self._tool_inspect_archive(arguments, repo_path, observations)
            elif tool == "send_progress":
                result = self._tool_send_progress(arguments, progress_callback, observations)
            elif tool == "retrieve_rag":
                result = self._tool_retrieve_rag(arguments, rag_callback, observations)
            elif tool == "get_review_history":
                result = self._tool_get_review_history(clone_url, observations)
            elif tool == "update_review_history":
                result = self._tool_update_review_history(
                    arguments,
                    clone_url=clone_url,
                    topic_title=topic_title,
                    observations=observations,
                )
            elif tool == "run_tests":
                result = self._tool_run_tests(arguments, repo_path, observations)
            elif tool == "git_history":
                result = self._tool_git_history(arguments, repo_path, observations)
            elif tool == "fetch_url":
                result = self._tool_fetch_url(arguments, repo_path, observations)
            elif tool == "code_metrics":
                result = self._tool_code_metrics(arguments, repo_path, observations)
            elif tool == "validate_structure":
                result = self._tool_validate_structure(
                    arguments, repo_path, observations
                )
            elif tool == "final_answer":
                if not history_checked:
                    result = {
                        "ok": False,
                        "error": "final_answer 前必须先调用 get_review_history",
                    }
                elif not history_action_taken:
                    result = {
                        "ok": False,
                        "error": "final_answer 前必须先调用 update_review_history",
                    }
                else:
                    # Enforce required tools workflow
                    missing = _check_required_tools(tools_called or set())
                    if missing:
                        result = {
                            "ok": False,
                            "error": (
                                f"final_answer 前必须先调用以下工具：{', '.join(missing)}。"
                                "请先调用这些工具获取数据，再输出最终评价。"
                            ),
                        }
                    else:
                        message = str(arguments.get("message") or "").strip()
                        # Validate report structure (max 2 rejections to prevent infinite loop)
                        rs = rejection_state or {"final_answer_rejections": 0}
                        structure_errors = _validate_report_structure(message)
                        if structure_errors and rs["final_answer_rejections"] < 2:
                            # Inject the full report template for the model to follow
                            template = _load_report_template()
                            result = {
                                "ok": False,
                                "error": template,
                            }
                            rs["final_answer_rejections"] += 1
                        else:
                            # Accept (either valid or max retries reached)
                            result = {
                                "ok": bool(message),
                                "message": message or "final_answer.message 不能为空",
                            }
            else:
                result = {"ok": False, "error": f"未知工具：{tool}"}
        except Exception as exc:  # noqa: BLE001 - tool loop returns observations
            result = {"ok": False, "error": str(exc)}
        if tool_log_callback is not None:
            tool_log_callback(tool, arguments, result)
        return result

    def _tool_clone_repository(
        self,
        arguments: dict[str, Any],
        clone_url: str,
        repo_path: Path,
        observations: list[RepositoryToolObservation],
    ) -> dict[str, Any]:
        requested_url = str(arguments.get("url") or clone_url)
        normalized_url, _ = normalize_github_url(requested_url)
        if normalized_url != clone_url:
            return {"ok": False, "error": "只能克隆当前 QQ 消息中的 GitHub 仓库"}
        if repo_path.exists():
            return {"ok": True, "already_cloned": True, "path": str(repo_path)}
        self._clone(clone_url, repo_path, observations)
        return {"ok": True, "path": str(repo_path)}

    def _tool_list_files(
        self,
        arguments: dict[str, Any],
        repo_path: Path,
        observations: list[RepositoryToolObservation],
        files: list[str],
    ) -> dict[str, Any]:
        if not repo_path.exists():
            return {"ok": False, "error": "请先调用 clone_repository"}
        max_files = int(arguments.get("max_files") or self.max_listed_files)
        max_files = max(1, min(max_files, self.max_listed_files))
        files[:] = _safe_files(repo_path, max_files=max_files)
        observations.append(
            RepositoryToolObservation(
                tool="list_files",
                input={"max_files": max_files},
                output=f"{len(files)} files listed",
            )
        )
        return {"ok": True, "count": len(files), "files": files}

    def _tool_read_file(
        self,
        arguments: dict[str, Any],
        repo_path: Path,
        observations: list[RepositoryToolObservation],
        evidence: list[RepositoryFileEvidence],
    ) -> dict[str, Any]:
        if not repo_path.exists():
            return {"ok": False, "error": "请先调用 clone_repository"}
        rel = str(arguments.get("path") or "")
        if not rel:
            return {"ok": False, "error": "read_file.path 不能为空"}
        if len(evidence) >= self.max_inspected_files:
            return {"ok": False, "error": "已达到最大读取文件数量"}
        if _evidence_chars(evidence) >= self.max_total_chars:
            return {"ok": False, "error": "已达到最大读取字符数"}
        new_evidence = self._read_selected_files(repo_path, [rel], observations)
        if not new_evidence:
            return {"ok": False, "error": f"文件不可读取或不是受支持的文本文件：{rel}"}
        evidence.extend(new_evidence)
        item = new_evidence[0]
        return {"ok": True, "path": item.path, "chars": item.chars, "content": item.content}

    def _tool_inspect_archive(
        self,
        arguments: dict[str, Any],
        repo_path: Path,
        observations: list[RepositoryToolObservation],
    ) -> dict[str, Any]:
        rel = str(arguments.get("path") or "")
        if not rel:
            return {"ok": False, "error": "inspect_archive.path 不能为空"}
        path = _safe_join(repo_path, rel)
        if path is None or not path.exists() or not path.is_file():
            return {"ok": False, "error": f"压缩包不存在：{rel}"}
        names = _inspect_archive_names(path)
        observations.append(
            RepositoryToolObservation(
                tool="inspect_archive",
                input={"path": rel},
                output=f"{len(names)} archive entries listed",
            )
        )
        return {"ok": True, "path": rel, "entries": names[:200], "count": len(names)}

    def _tool_view_document_page(
        self,
        arguments: dict[str, Any],
        repo_path: Path,
        observations: list[RepositoryToolObservation],
        chat_client: OpenAICompatibleChatClient | None,
        messages: list[ChatMessage] | None,
    ) -> dict[str, Any]:
        """Render a document page to image and send to the vision model for analysis."""
        rel = str(arguments.get("path") or "")
        page = int(arguments.get("page", 1))
        if not rel:
            return {"ok": False, "error": "view_document_page.path 不能为空"}
        path = _safe_join(repo_path, rel)
        if path is None or not path.exists() or not path.is_file():
            return {"ok": False, "error": f"文件不存在：{rel}"}
        suffix = path.suffix.lower()
        if suffix not in {".pdf", ".pptx", ".ppt", ".docx", ".png", ".jpg", ".jpeg"}:
            return {"ok": False, "error": f"不支持视觉查看该格式：{suffix}，请用 read_file"}
        if chat_client is None or not chat_client.api_key_configured:
            return {"ok": False, "error": "视觉模型未配置 API Key"}

        # Render to image
        image_data = _render_document_page(path, page)
        if image_data is None:
            return {"ok": False, "error": f"无法渲染 {rel} 第 {page} 页"}

        # Call vision model
        b64 = base64.b64encode(image_data).decode("ascii")
        vision_content: list[dict[str, Any]] = [
            {"type": "text", "text": f"请描述这个文档页面的内容（{rel} 第{page}页）。"
             "关注：标题、结构、关键数据、图表、公式、代码片段等。"},
            {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{b64}"}},
        ]
        try:
            vision_result = chat_client.chat(
                ChatCompletionRequest(
                    messages=[ChatMessage(role="user", content=vision_content)],
                    temperature=0.1,
                    max_tokens=1500,
                )
            )
            description = vision_result.content.strip()[:3000]
        except Exception as exc:  # noqa: BLE001
            description = f"视觉模型调用失败：{exc}"

        observations.append(
            RepositoryToolObservation(
                tool="view_document_page",
                input={"path": rel, "page": page},
                output=f"vision: {len(description)} chars",
            )
        )
        return {"ok": True, "path": rel, "page": page, "description": description}

    def _tool_send_progress(
        self,
        arguments: dict[str, Any],
        progress_callback: RepositoryProgressCallback | None,
        observations: list[RepositoryToolObservation],
    ) -> dict[str, Any]:
        message = str(arguments.get("message") or "").strip()[:220]
        if not message:
            return {"ok": False, "error": "send_progress.message 不能为空"}
        if progress_callback is not None:
            progress_callback(message)
        observations.append(
            RepositoryToolObservation(
                tool="send_progress",
                input={"message": message},
                output="success",
            )
        )
        return {"ok": True, "sent": progress_callback is not None, "message": message}

    def _tool_retrieve_rag(
        self,
        arguments: dict[str, Any],
        rag_callback: RepositoryRagCallback | None,
        observations: list[RepositoryToolObservation],
    ) -> dict[str, Any]:
        query = str(arguments.get("query") or "").strip()
        if not query:
            return {"ok": False, "error": "retrieve_rag.query 不能为空"}
        evidence = rag_callback(query) if rag_callback is not None else []
        observations.append(
            RepositoryToolObservation(
                tool="retrieve_rag",
                input={"query": query},
                output=f"{len(evidence)} rag evidence returned",
            )
        )
        return {"ok": True, "query": query, "evidence": evidence}

    def _tool_get_review_history(
        self,
        clone_url: str,
        observations: list[RepositoryToolObservation],
    ) -> dict[str, Any]:
        record = self.history_store.get(clone_url)
        observations.append(
            RepositoryToolObservation(
                tool="get_review_history",
                input={"url": clone_url},
                output="found" if record else "not found",
            )
        )
        return {"ok": True, "record": record.model_dump() if record else None}

    def _tool_update_review_history(
        self,
        arguments: dict[str, Any],
        *,
        clone_url: str,
        topic_title: str,
        observations: list[RepositoryToolObservation],
    ) -> dict[str, Any]:
        review = str(arguments.get("review") or arguments.get("message") or "").strip()
        improved = bool(arguments.get("improved", True))
        score = _optional_float(arguments.get("score"))
        topic_name = str(arguments.get("topic_name") or topic_title or "未命名课题")
        tool_summary = str(arguments.get("tool_summary") or "")
        if not review:
            return {"ok": False, "error": "update_review_history.review 不能为空"}
        result = self.history_store.update(
            repo_url=clone_url,
            topic_name=topic_name,
            review=review,
            score=score,
            improved=improved,
            tool_summary=tool_summary,
        )
        observations.append(
            RepositoryToolObservation(
                tool="update_review_history",
                input={"url": clone_url, "improved": improved},
                output="updated" if result.updated else "unchanged",
            )
        )
        return {"ok": True, **result.model_dump()}

    def _tool_run_tests(
        self,
        arguments: dict[str, Any],
        repo_path: Path,
        observations: list[RepositoryToolObservation],
    ) -> dict[str, Any]:
        """Run tests in sandbox with subprocess."""
        if not repo_path.exists():
            return {"ok": False, "error": "请先调用 clone_repository"}
        command = str(arguments.get("command") or "pytest")
        timeout = min(int(arguments.get("timeout") or 30), 60)
        # Security: block dangerous commands
        _DANGEROUS_TOKENS = {"rm", "sudo", "curl", "wget", "chmod", "chown",
                             "mkfs", "dd", "shutdown", "reboot", "kill"}
        cmd_lower = command.lower()
        for token in _DANGEROUS_TOKENS:
            if re.search(rf"\b{token}\b", cmd_lower):
                return {
                    "ok": False,
                    "error": f"禁止执行包含危险命令的测试：{token}",
                }
        # Filter sensitive env vars
        env = {
            k: v for k, v in os.environ.items()
            if not any(
                s in k.upper()
                for s in ("API_KEY", "SECRET", "TOKEN", "PASSWORD", "CREDENTIAL")
            )
        }
        env["HOME"] = os.environ.get("HOME", "/tmp")
        try:
            proc = subprocess.run(
                command,
                shell=True,
                cwd=str(repo_path),
                timeout=timeout,
                capture_output=True,
                text=True,
                env=env,
            )
            output = (proc.stdout + proc.stderr)[-3000:]
            passed = proc.returncode == 0
            result = {
                "ok": True,
                "exit_code": proc.returncode,
                "output": output,
                "passed": passed,
            }
        except subprocess.TimeoutExpired:
            result = {
                "ok": True,
                "exit_code": -1,
                "output": f"测试超时（{timeout}秒）",
                "passed": False,
            }
        except Exception as exc:  # noqa: BLE001
            result = {"ok": False, "error": f"执行测试失败：{exc}"}
        observations.append(
            RepositoryToolObservation(
                tool="run_tests",
                input={"command": command, "timeout": timeout},
                output=f"exit_code={result.get('exit_code', '?')}",
            )
        )
        return result

    def _tool_git_history(
        self,
        arguments: dict[str, Any],
        repo_path: Path,
        observations: list[RepositoryToolObservation],
    ) -> dict[str, Any]:
        """Analyze git commit history."""
        if not repo_path.exists():
            return {"ok": False, "error": "请先调用 clone_repository"}
        max_commits = min(int(arguments.get("max_commits") or 50), 200)

        # If this is a shallow clone, unshallow it first to get full history
        shallow_file = repo_path / ".git" / "shallow"
        if shallow_file.exists():
            try:
                subprocess.run(
                    ["git", "fetch", "--unshallow"],
                    cwd=str(repo_path),
                    capture_output=True,
                    text=True,
                    timeout=60,
                    env={**os.environ, "GIT_TERMINAL_PROMPT": "0"},
                )
            except Exception:  # noqa: BLE001
                # If unshallow fails, try fetching full history another way
                try:
                    subprocess.run(
                        ["git", "fetch", "--depth=2147483647"],
                        cwd=str(repo_path),
                        capture_output=True,
                        text=True,
                        timeout=60,
                        env={**os.environ, "GIT_TERMINAL_PROMPT": "0"},
                    )
                except Exception:  # noqa: BLE001
                    pass

        try:
            proc = subprocess.run(
                [
                    "git", "log",
                    "--format=%H|%an|%ae|%aI|%s",
                    f"-n{max_commits}",
                ],
                cwd=str(repo_path),
                capture_output=True,
                text=True,
                timeout=15,
            )
            if proc.returncode != 0:
                return {"ok": False, "error": "git log 失败"}
        except Exception as exc:  # noqa: BLE001
            return {"ok": False, "error": f"git log 异常：{exc}"}
        lines = [ln for ln in proc.stdout.strip().splitlines() if ln.strip()]
        if not lines:
            return {"ok": True, "commit_count": 0, "contributors": [],
                    "recent_commits": []}
        commits_data: list[dict[str, str]] = []
        contributor_counter: Counter[str] = Counter()
        contributor_emails: dict[str, str] = {}
        late_night_count = 0
        date_strs: list[str] = []
        day_counter: Counter[str] = Counter()
        for line in lines:
            parts = line.split("|", 4)
            if len(parts) < 5:
                continue
            hash_, author, email, date_str, message = parts
            commits_data.append({
                "hash": hash_[:8],
                "author": author,
                "date": date_str,
                "message": message,
            })
            contributor_counter[author] += 1
            contributor_emails[author] = email
            date_strs.append(date_str)
            # Parse hour for late night ratio
            try:
                dt = datetime.fromisoformat(date_str)
                if 0 <= dt.hour < 6:
                    late_night_count += 1
                day_counter[dt.strftime("%Y-%m-%d")] += 1
            except (ValueError, TypeError):
                pass
        commit_count = len(commits_data)
        contributors = [
            {"name": name, "email": contributor_emails.get(name, ""),
             "commits": count}
            for name, count in contributor_counter.most_common()
        ]
        # Calculate span
        first_commit = date_strs[-1] if date_strs else ""
        last_commit = date_strs[0] if date_strs else ""
        span_days = 0
        commits_per_week = 0.0
        if first_commit and last_commit:
            try:
                first_dt = datetime.fromisoformat(first_commit)
                last_dt = datetime.fromisoformat(last_commit)
                span_days = max((last_dt - first_dt).days, 1)
                commits_per_week = round(
                    commit_count / (span_days / 7.0), 2
                ) if span_days > 0 else float(commit_count)
            except (ValueError, TypeError):
                pass
        late_night_ratio = round(
            late_night_count / commit_count, 3
        ) if commit_count > 0 else 0.0
        single_day_ratio = round(
            max(day_counter.values()) / commit_count, 3
        ) if day_counter and commit_count > 0 else 0.0
        result = {
            "ok": True,
            "commit_count": commit_count,
            "contributors": contributors,
            "first_commit": first_commit,
            "last_commit": last_commit,
            "span_days": span_days,
            "commits_per_week": commits_per_week,
            "recent_commits": commits_data[:10],
            "late_night_ratio": late_night_ratio,
            "single_day_ratio": single_day_ratio,
        }
        observations.append(
            RepositoryToolObservation(
                tool="git_history",
                input={"max_commits": max_commits},
                output=f"{commit_count} commits, {len(contributors)} contributors",
            )
        )
        return result

    def _tool_fetch_url(
        self,
        arguments: dict[str, Any],
        repo_path: Path,
        observations: list[RepositoryToolObservation],
    ) -> dict[str, Any]:
        """Fetch URL content with httpx."""
        url = str(arguments.get("url") or "").strip()
        timeout = min(int(arguments.get("timeout") or 10), 20)
        if not url:
            return {"ok": False, "error": "fetch_url.url 不能为空"}
        # Security: only allow http/https
        parsed = urllib.parse.urlparse(url)
        if parsed.scheme not in ("http", "https"):
            return {"ok": False, "error": "仅支持 http/https 协议"}
        # Block private/local addresses
        hostname = parsed.hostname or ""
        if hostname in ("localhost", "127.0.0.1", "0.0.0.0", "::1"):
            return {"ok": False, "error": "禁止访问本地地址"}
        try:
            addr = ipaddress.ip_address(hostname)
            if addr.is_private or addr.is_loopback or addr.is_reserved:
                return {"ok": False, "error": "禁止访问内网地址"}
        except ValueError:
            # Not a raw IP, check for common internal patterns
            if hostname.endswith(".local") or hostname.startswith("10."):
                return {"ok": False, "error": "禁止访问内网地址"}
        try:
            import httpx
            with httpx.Client(timeout=timeout, follow_redirects=True) as client:
                resp = client.get(url, headers={"User-Agent": "AgentReviewer/1.0"})
            status_code = resp.status_code
            content_type = resp.headers.get("content-type", "")
            text = resp.text[:5000] if len(resp.text) > 5000 else resp.text
            # Extract title from HTML
            title = ""
            if "html" in content_type.lower():
                m = re.search(
                    r"<title[^>]*>(.*?)</title>", text, re.IGNORECASE | re.DOTALL
                )
                if m:
                    title = m.group(1).strip()[:200]
            result: dict[str, Any] = {
                "ok": True,
                "status_code": status_code,
                "content_type": content_type,
                "text": text,
                "title": title,
            }
        except ImportError:
            result = {"ok": False, "error": "httpx 未安装"}
        except Exception as exc:  # noqa: BLE001
            result = {"ok": False, "error": f"请求失败：{exc}"}
        observations.append(
            RepositoryToolObservation(
                tool="fetch_url",
                input={"url": url, "timeout": timeout},
                output=f"status={result.get('status_code', '?')}",
            )
        )
        return result

    def _tool_code_metrics(
        self,
        arguments: dict[str, Any],
        repo_path: Path,
        observations: list[RepositoryToolObservation],
    ) -> dict[str, Any]:
        """Compute code metrics for the repository."""
        if not repo_path.exists():
            return {"ok": False, "error": "请先调用 clone_repository"}
        total_files = 0
        total_lines = 0
        languages: dict[str, dict[str, int]] = {}
        test_files = 0
        max_file_path = ""
        max_file_lines = 0
        dependency_files: list[str] = []
        _DEP_NAMES = {
            "requirements.txt", "pyproject.toml", "setup.py", "setup.cfg",
            "package.json", "package-lock.json", "yarn.lock", "pnpm-lock.yaml",
            "go.mod", "go.sum", "cargo.toml", "cargo.lock",
            "pom.xml", "build.gradle", "gemfile", "composer.json",
        }
        for path in repo_path.rglob("*"):
            rel = path.relative_to(repo_path)
            if any(part in _SKIP_DIRS for part in rel.parts):
                continue
            if not path.is_file() or path.is_symlink():
                continue
            total_files += 1
            name_lower = path.name.lower()
            # Check dependency files
            if name_lower in _DEP_NAMES:
                dependency_files.append(rel.as_posix())
            # Check test files
            if "test" in name_lower or "spec" in name_lower:
                test_files += 1
            # Count lines for text files
            suffix = path.suffix.lower()
            if suffix in _TEXT_SUFFIXES:
                try:
                    line_count = len(
                        path.read_text(encoding="utf-8", errors="ignore")
                        .splitlines()
                    )
                except OSError:
                    line_count = 0
                total_lines += line_count
                if suffix not in languages:
                    languages[suffix] = {"files": 0, "lines": 0}
                languages[suffix]["files"] += 1
                languages[suffix]["lines"] += line_count
                if line_count > max_file_lines:
                    max_file_lines = line_count
                    max_file_path = rel.as_posix()
        # Check special files/dirs
        has_ci = (
            (repo_path / ".github" / "workflows").is_dir()
            or (repo_path / ".gitlab-ci.yml").is_file()
        )
        has_docker = (repo_path / "Dockerfile").is_file() or (
            repo_path / "dockerfile"
        ).is_file()
        has_readme = any(
            (repo_path / n).is_file()
            for n in ("README.md", "readme.md", "README.rst", "README.txt",
                      "README")
        )
        has_license = any(
            (repo_path / n).is_file()
            for n in ("LICENSE", "LICENSE.md", "LICENSE.txt", "LICENCE",
                      "license")
        )
        avg_file_lines = (
            round(total_lines / total_files, 1) if total_files > 0 else 0
        )
        test_ratio = (
            round(test_files / total_files, 3) if total_files > 0 else 0.0
        )
        result = {
            "ok": True,
            "total_files": total_files,
            "total_lines": total_lines,
            "languages": languages,
            "test_files": test_files,
            "test_ratio": test_ratio,
            "has_ci": has_ci,
            "has_docker": has_docker,
            "has_readme": has_readme,
            "has_license": has_license,
            "avg_file_lines": avg_file_lines,
            "max_file": {"path": max_file_path, "lines": max_file_lines},
            "dependency_files": dependency_files,
        }
        observations.append(
            RepositoryToolObservation(
                tool="code_metrics",
                input={},
                output=(
                    f"{total_files} files, {total_lines} lines, "
                    f"{len(languages)} languages"
                ),
            )
        )
        return result

    def _tool_validate_structure(
        self,
        arguments: dict[str, Any],
        repo_path: Path,
        observations: list[RepositoryToolObservation],
    ) -> dict[str, Any]:
        """Validate document structure against expected sections."""
        if not repo_path.exists():
            return {"ok": False, "error": "请先调用 clone_repository"}
        rel = str(arguments.get("path") or "")
        doc_type = str(arguments.get("type") or "report")
        if not rel:
            return {"ok": False, "error": "validate_structure.path 不能为空"}
        path = _safe_join(repo_path, rel)
        if path is None or not path.exists() or not path.is_file():
            return {"ok": False, "error": f"文件不存在：{rel}"}
        # Read file content
        try:
            content = path.read_text(encoding="utf-8", errors="ignore")
        except OSError as exc:
            return {"ok": False, "error": f"文件读取失败：{exc}"}
        # Define required sections for each type
        _REQUIRED_SECTIONS: dict[str, list[list[str]]] = {
            "report": [
                ["摘要", "abstract"],
                ["背景", "introduction", "引言"],
                ["方法", "method", "methodology", "方案"],
                ["实验", "experiment", "实现"],
                ["结果", "result", "成果"],
                ["结论", "conclusion", "总结"],
            ],
            "paper": [
                ["abstract"],
                ["introduction"],
                ["related work", "相关工作"],
                ["method", "methodology", "approach", "方法"],
                ["experiment", "evaluation", "实验"],
                ["conclusion", "结论"],
                ["references", "参考文献"],
            ],
            "presentation": [
                ["标题", "title"],
                ["目录", "outline", "contents", "agenda"],
                ["方法", "method", "approach", "方案"],
                ["结果", "result", "成果", "实验"],
                ["总结", "conclusion", "summary"],
            ],
        }
        required = _REQUIRED_SECTIONS.get(doc_type, _REQUIRED_SECTIONS["report"])
        # Extract headings from markdown
        headings: list[str] = []
        for line in content.splitlines():
            stripped = line.strip()
            if stripped.startswith("#"):
                heading_text = stripped.lstrip("#").strip().lower()
                headings.append(heading_text)
        # For presentation: also count slides (## or --- separators)
        slide_count = 0
        if doc_type == "presentation":
            slide_count = max(
                len([h for h in content.splitlines()
                     if h.strip().startswith("## ")]),
                content.count("---") // 2,
                len(headings),
            )
        # Match found sections
        found_sections: list[str] = []
        missing_sections: list[str] = []
        content_lower = content.lower()
        for section_aliases in required:
            matched = False
            for alias in section_aliases:
                # Check headings first
                if any(alias in h for h in headings):
                    matched = True
                    break
                # Fallback: check content for section-like patterns
                if f"# {alias}" in content_lower or f"## {alias}" in content_lower:
                    matched = True
                    break
            if matched:
                found_sections.append(section_aliases[0])
            else:
                missing_sections.append(section_aliases[0])
        completeness = round(
            len(found_sections) / len(required), 2
        ) if required else 0.0
        structure_valid = completeness >= 0.6
        # Extra check for presentation: needs at least 5 slides
        if doc_type == "presentation" and slide_count < 5:
            structure_valid = False
        result: dict[str, Any] = {
            "ok": True,
            "found_sections": found_sections,
            "missing_sections": missing_sections,
            "completeness": completeness,
            "structure_valid": structure_valid,
        }
        if doc_type == "presentation":
            result["slide_count"] = slide_count
        observations.append(
            RepositoryToolObservation(
                tool="validate_structure",
                input={"path": rel, "type": doc_type},
                output=(
                    f"completeness={completeness}, "
                    f"valid={structure_valid}"
                ),
            )
        )
        return result

    def _clone(
        self,
        clone_url: str,
        destination: Path,
        observations: list[RepositoryToolObservation],
    ) -> None:
        observations.append(
            RepositoryToolObservation(
                tool="clone_repository",
                input={"url": clone_url, "depth": 1},
                output="running",
            )
        )
        try:
            subprocess.run(
                ["git", "clone", "--depth", "1", clone_url, str(destination)],
                check=True,
                timeout=self.clone_timeout_seconds,
                capture_output=True,
                text=True,
                env={**os.environ, "GIT_TERMINAL_PROMPT": "0"},
            )
            observations[-1].output = "success"
        except FileNotFoundError as exc:
            observations[-1].output = "failed: git not found"
            raise RepositoryAnalysisError("git is required to analyze repository links") from exc
        except subprocess.TimeoutExpired as exc:
            observations[-1].output = "failed: timeout"
            raise RepositoryAnalysisError("repository clone timed out") from exc
        except subprocess.CalledProcessError as exc:
            detail = (exc.stderr or exc.stdout or "git clone failed").strip()[-500:]
            observations[-1].output = f"failed: {detail}"
            raise RepositoryAnalysisError(detail) from exc

    def _read_selected_files(
        self,
        repo_path: Path,
        files: list[str],
        observations: list[RepositoryToolObservation],
    ) -> list[RepositoryFileEvidence]:
        evidence: list[RepositoryFileEvidence] = []
        current = 0
        for rel in files:
            if current >= self.max_total_chars:
                break
            path = _safe_join(repo_path, rel)
            if path is None or not _is_readable_text_file(rel, path):
                continue
            try:
                content = path.read_text(encoding="utf-8", errors="ignore")[: self.max_file_chars]
            except OSError as exc:
                observations.append(
                    RepositoryToolObservation(
                        tool="read_file",
                        input={"path": rel},
                        output=f"failed: {exc}",
                    )
                )
                continue
            remaining = self.max_total_chars - current
            content = content[:remaining]
            current += len(content)
            evidence.append(RepositoryFileEvidence(path=rel, chars=len(content), content=content))
            observations.append(
                RepositoryToolObservation(
                    tool="read_file",
                    input={"path": rel},
                    output=f"{len(content)} chars",
                )
            )
        return evidence

    def _append_cleanup_observation(
        self,
        observations: list[RepositoryToolObservation],
    ) -> None:
        observations.append(
            RepositoryToolObservation(
                tool="cleanup_workspace",
                input={},
                output="temporary source directory removed",
            )
        )


def _format_observation_cn(item: RepositoryToolObservation) -> str:
    tool_names = {
        "clone_repository": "克隆仓库",
        "list_files": "列出文件",
        "read_file": "读取文件",
        "inspect_archive": "检查压缩包",
        "send_progress": "发送进度",
        "retrieve_rag": "检索参考资料",
        "get_review_history": "读取历史评价",
        "update_review_history": "更新历史评价",
        "cleanup_workspace": "清理临时工作区",
        "run_tests": "运行测试",
        "git_history": "分析提交历史",
        "fetch_url": "访问URL",
        "code_metrics": "代码统计",
        "validate_structure": "文档结构验证",
    }
    tool_name = tool_names.get(item.tool, item.tool)
    output = _translate_observation_output(item.output)
    return f"- 工具：{tool_name}；参数：{item.input}；结果：{output}"


def _translate_observation_output(output: str) -> str:
    if output == "running":
        return "运行中"
    if output == "success":
        return "成功"
    if output == "temporary source directory removed":
        return "临时源码目录已清理"
    if output.endswith(" files listed"):
        return "已列出 " + output.removesuffix(" files listed") + " 个文件"
    if output.endswith(" chars"):
        return "已读取 " + output.removesuffix(" chars") + " 个字符"
    if output.startswith("failed:"):
        return "失败：" + output.removeprefix("failed:").strip()
    return output


def _can_call_model(chat_client: OpenAICompatibleChatClient | None) -> bool:
    return chat_client is not None and chat_client.api_key_configured


def _safe_files(root: Path, *, max_files: int) -> list[str]:
    results: list[str] = []
    for path in root.rglob("*"):
        rel = path.relative_to(root)
        if any(part in _SKIP_DIRS for part in rel.parts):
            continue
        if not path.is_file() or path.is_symlink():
            continue
        results.append(rel.as_posix())
        if len(results) >= max_files:
            break
    return sorted(results)


def _initial_file_selection(files: list[str], limit: int) -> list[str]:
    ranked = sorted(files, key=_file_priority)
    return [item for item in ranked if _likely_text_path(item)][:limit]


def _file_priority(path: str) -> tuple[int, int, str]:
    lower = path.lower()
    name = Path(path).name.lower()
    score = 100
    if name in _IMPORTANT_NAMES:
        score -= 80
    if lower.startswith(".github/workflows/"):
        score -= 70
    if "test" in lower or "spec" in lower:
        score -= 45
    if any(part in lower for part in ["src/", "app/", "lib/", "server/", "api/"]):
        score -= 35
    return score, len(Path(path).parts), path


def _likely_text_path(path: str) -> bool:
    suffix = Path(path).suffix.lower()
    name = Path(path).name.lower()
    return suffix in _TEXT_SUFFIXES or name in _IMPORTANT_NAMES


def _is_readable_text_file(rel: str, path: Path) -> bool:
    return path.exists() and path.is_file() and _likely_text_path(rel) and not path.is_symlink()


def _evidence_chars(evidence: list[RepositoryFileEvidence]) -> int:
    return sum(item.chars for item in evidence)


def _join_limited(items: list[str], limit: int) -> str:
    text = "\n".join(items)
    return text[:limit]


# Required tools that must be called before final_answer
_REQUIRED_TOOLS = {"clone_repository", "list_files", "code_metrics", "git_history"}


def _check_required_tools(tools_called: set[str]) -> list[str]:
    """Return list of required tools that haven't been called yet."""
    missing = _REQUIRED_TOOLS - tools_called
    return sorted(missing) if missing else []


# Required sections in the final report — check flexibly (substring match)
_REQUIRED_REPORT_SECTIONS = [
    "综合评分",
    "终评结论",
    "问题",      # matches "主要问题", "主要不足", "问题与不足" etc.
    "建议",      # matches "修改建议", "建议", "改进建议" etc.
]


def _validate_report_structure(message: str) -> list[str]:
    """Check that the final answer contains all required sections.

    Uses flexible substring matching — accepts ## headers, 【】 brackets,
    or numbered formats like "一、综合评分".
    Returns list of issues, or empty list if all valid.
    """
    if not message or len(message) < 200:
        return ["报告内容过短（至少200字）"]
    missing = []
    for section in _REQUIRED_REPORT_SECTIONS:
        if section not in message:
            missing.append(section)
    return missing


_REPORT_TEMPLATE_CACHE: str | None = None


def _load_report_template() -> str:
    """Load the report template file, used when final_answer structure fails.

    This is the key cc-haha-inspired pattern: inject detailed correction
    instructions with the exact template to follow, rather than just saying
    'structure is wrong'. This gives the model a clear target to hit.
    """
    global _REPORT_TEMPLATE_CACHE
    # Always reload (template may be updated without restart)
    template_path = Path("data/evaluation-report-template.txt")
    if template_path.exists():
        _REPORT_TEMPLATE_CACHE = template_path.read_text(encoding="utf-8").strip()
    else:
        _REPORT_TEMPLATE_CACHE = (
            "报告结构不完整。final_answer 必须包含以下章节："
            "综合评分、终评结论、材料完整性检查、代码工程分析、"
            "开发过程分析、分项评分、主要问题（至少5条）、修改建议（至少6条）、下一步优先级。"
            "请重新输出完整报告。"
        )
    return _REPORT_TEMPLATE_CACHE


def _extract_json_object(content: str) -> dict[str, Any]:
    """Extract the first valid top-level JSON object from content.

    Uses bracket-depth matching instead of naive rfind to handle
    nested braces inside string values (e.g. long review text).
    """
    start = content.find("{")
    if start < 0:
        return {}
    # Try progressively longer substrings from the first {
    depth = 0
    in_string = False
    escape_next = False
    for i in range(start, len(content)):
        ch = content[i]
        if escape_next:
            escape_next = False
            continue
        if ch == "\\":
            if in_string:
                escape_next = True
            continue
        if ch == '"' and not escape_next:
            in_string = not in_string
            continue
        if in_string:
            continue
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                try:
                    parsed = json.loads(content[start : i + 1])
                    if isinstance(parsed, dict):
                        return parsed
                except json.JSONDecodeError:
                    pass
                # Keep looking for another valid closing
                break
    # Fallback: try the naive approach
    end = content.rfind("}")
    if end > start:
        try:
            parsed = json.loads(content[start : end + 1])
            return parsed if isinstance(parsed, dict) else {}
        except json.JSONDecodeError:
            pass
    return {}


def _tool_loop_task_message(
    *,
    url: str,
    topic_title: str,
    topic_goal: str,
    rule_evaluation: ProjectEvaluationResult | None,
    progress_instruction: str = "",
) -> str:
    rule_text = "无"
    if rule_evaluation is not None:
        rule_text = (
            f"自动规则预评分（仅供参考，不作为你的最终评分依据）："
            f"{rule_evaluation.overall_score}/100；"
            f"摘要：{rule_evaluation.summary}。"
            f"注意：你必须独立根据工具读取的真实内容和提示词中的评分标准给出评分，"
            f"不要被此预评分影响。"
        )
    progress_section = progress_instruction or (
        "进度汇报：在 clone 成功、列出文件、每读 3-5 个文件、检索参考资料、"
        "查完历史记录等关键节点，都要调用 send_progress 向用户汇报当前进展。"
        "汇报内容要基于刚完成的真实工具结果，简短自然，不要提前下结论。"
    )
    return (
        "当前任务：请通过工具循环自主审查 GitHub 仓库，并最终给出可直接发送 QQ 的评价。\n"
        "你每次只能返回一个 JSON 工具调用，不要输出 JSON 之外的文字。\n\n"
        "【强制工作流程 — 必须按顺序执行，不可跳过】\n"
        "第1步：clone_repository — 克隆仓库\n"
        "第2步：list_files — 查看完整文件目录\n"
        "第3步：code_metrics — 获取代码规模、语言分布、测试、CI 等指标\n"
        "第4步：git_history — 获取提交历史（提交数、跨度、贡献者、凌晨比例等）\n"
        "第5步：read_file — 逐个读取 README、核心代码、配置、测试文件\n"
        "第6步：view_document_page — 对 PDF/PPTX/DOCX 使用视觉查看\n"
        "第7步：get_review_history — 查询历史评价\n"
        "第8步：update_review_history — 写入评价记录\n"
        "第9步：final_answer — 输出最终评价\n\n"
        "【工具调用约束】\n"
        "- 系统强制要求：clone_repository、list_files、code_metrics、git_history "
        "这四个工具必须全部调用成功后才允许调用 final_answer\n"
        "- 如果尝试跳过任何必需工具直接调用 final_answer，将收到错误并被要求补充\n"
        "- get_review_history 和 update_review_history 也是 final_answer 的前置条件\n\n"
        "可用工具：\n"
        "1. clone_repository：参数 {\"url\": \"仓库地址\"}\n"
        "2. list_files：参数 {\"max_files\": 1200}（可选 path 查看子目录）\n"
        "3. read_file：参数 {\"path\": \"仓库内相对路径\"}\n"
        "4. view_document_page：参数 {\"path\": \"文件路径\", \"page\": 页码}，"
        "用视觉能力查看 PDF/PPTX/DOCX/图片文件的某一页\n"
        "5. inspect_archive：参数 {\"path\": \"仓库内压缩包相对路径\"}\n"
        "6. retrieve_rag：参数 {\"query\": \"要检索的参考资料问题\"}\n"
        "7. get_review_history：参数 {}，最终评价前必须调用\n"
        "8. update_review_history：参数 {\"topic_name\": \"课题名\", \"score\": 评分, "
        "\"review\": \"评价内容\", \"improved\": true/false, "
        "\"tool_summary\": \"工具依据\"}，final_answer 前必须调用\n"
        "9. send_progress：参数 {\"message\": \"要发给用户的简短进度\"}\n"
        "10. run_tests：参数 {\"command\": \"pytest\", \"timeout\": 30}，"
        "在仓库中运行测试命令\n"
        "11. git_history：参数 {\"max_commits\": 50}，"
        "分析 Git 提交历史（必须调用！报告中开发过程数据来源于此）\n"
        "12. fetch_url：参数 {\"url\": \"https://...\", \"timeout\": 10}，"
        "访问外部 URL 获取页面内容\n"
        "13. code_metrics：参数 {}，"
        "统计仓库代码指标（必须调用！报告中代码工程数据来源于此）\n"
        "14. validate_structure：参数 {\"path\": \"报告.md\", \"type\": \"report\"}，"
        "验证文档结构完整性\n"
        "15. final_answer：参数 {\"message\": \"最终 Markdown 格式评价\"}\n"
        "工具调用格式：{\"tool\": \"工具名\", \"arguments\": {...}}\n\n"
        "【文档查看策略】PDF/PPTX/DOCX 文件优先用 view_document_page，"
        "不要用 read_file（文本提取容易乱码）。\n\n"
        f"【进度汇报要求】{progress_section}\n\n"
        f"仓库地址：{url}\n"
        f"课题：{topic_title}\n"
        f"目标：{topic_goal}\n"
        f"规则评价参考：{rule_text}\n"
    )


def _invalid_tool_observation() -> str:
    return (
        "工具观察：模型输出不是合法工具调用。请只返回 JSON："
        "{\"tool\": \"工具名\", \"arguments\": {...}}"
    )


def _tool_observation_message(observation: dict[str, Any]) -> str:
    return "工具观察：" + json.dumps(observation, ensure_ascii=False)[:80_000]


def _render_document_page(path: Path, page: int) -> bytes | None:
    """Render a document page to PNG image bytes."""
    suffix = path.suffix.lower()
    # Direct images — just return the file bytes
    if suffix in {".png", ".jpg", ".jpeg"}:
        try:
            return path.read_bytes()
        except OSError:
            return None
    # PDF — use PyMuPDF
    if suffix == ".pdf":
        return _render_pdf_page(path, page)
    # PPTX — convert via PyMuPDF (PPTX→PDF first if libreoffice available, else try pymupdf)
    if suffix in {".pptx", ".ppt", ".docx"}:
        return _render_office_page(path, page)
    return None


def _render_pdf_page(path: Path, page: int) -> bytes | None:
    """Render a PDF page to PNG using PyMuPDF."""
    try:
        import fitz  # PyMuPDF
        doc = fitz.open(str(path))
        if page < 1 or page > len(doc):
            doc.close()
            return None
        page_obj = doc[page - 1]
        # Render at 2x for clarity
        pix = page_obj.get_pixmap(matrix=fitz.Matrix(2, 2))
        data = pix.tobytes("png")
        doc.close()
        return data
    except Exception:  # noqa: BLE001
        return None


def _render_office_page(path: Path, page: int) -> bytes | None:
    """Render PPTX/DOCX page: convert to PDF with libreoffice, then render."""
    try:
        import fitz  # PyMuPDF

        with tempfile.TemporaryDirectory() as tmpdir:
            subprocess.run(
                ["libreoffice", "--headless", "--convert-to", "pdf",
                 "--outdir", tmpdir, str(path)],
                check=True, timeout=30, capture_output=True,
            )
            pdf_name = path.stem + ".pdf"
            pdf_path = Path(tmpdir) / pdf_name
            if not pdf_path.exists():
                return None
            return _render_pdf_page(pdf_path, page)
    except (FileNotFoundError, subprocess.SubprocessError):
        # libreoffice not available — try opening directly with pymupdf
        try:
            import fitz
            doc = fitz.open(str(path))
            if page < 1 or page > len(doc):
                doc.close()
                return None
            page_obj = doc[page - 1]
            pix = page_obj.get_pixmap(matrix=fitz.Matrix(2, 2))
            data = pix.tobytes("png")
            doc.close()
            return data
        except Exception:  # noqa: BLE001
            return None


def _progress_instruction(level: str) -> str:
    """Generate progress reporting instruction based on verbosity level."""
    if level == "minimal":
        return (
            "进度汇报：仅在整体分析完成即将输出最终评价前，"
            "调用一次 send_progress 简要告知用户即将出结果。"
        )
    if level == "verbose":
        return (
            "进度汇报（详细模式）：你必须在以下每个阶段都调用 send_progress 向用户汇报：\n"
            "- clone 成功后：告诉用户已获取仓库，有多少文件\n"
            "- 列出文件后：告诉用户文件结构概况\n"
            "- 每读取 2-3 个关键文件后：告诉用户当前在看什么、初步印象\n"
            "- 检索参考资料后：告诉用户正在对比评价标准\n"
            "- 查询历史记录后：告诉用户是否有历史、是否有变化\n"
            "- 更新 Excel 后：告诉用户记录情况\n"
            "每条进度消息要简短（1-2句）、基于真实工具结果、自然口语化。"
            "不要等到最后才一次性汇报，用户希望实时了解你在做什么。"
        )
    # normal
    return (
        "进度汇报：在以下关键节点调用 send_progress：\n"
        "- clone 成功后\n"
        "- 读取了几个关键文件、有初步判断时\n"
        "- 查完历史记录、即将给出最终评价前\n"
        "共汇报 2-3 次即可，每次简短一句话。"
    )


def _optional_float(value: object) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _safe_join(root: Path, rel: str) -> Path | None:
    candidate = (root / rel).resolve()
    try:
        candidate.relative_to(root.resolve())
    except ValueError:
        return None
    return candidate


def _inspect_archive_names(path: Path) -> list[str]:
    suffixes = "".join(path.suffixes).lower()
    try:
        if path.suffix.lower() == ".zip":
            with zipfile.ZipFile(path) as archive:
                return archive.namelist()
        if path.suffix.lower() in {".tar", ".tgz"} or suffixes.endswith(".tar.gz"):
            with tarfile.open(path) as archive:
                return archive.getnames()
    except (OSError, tarfile.TarError, zipfile.BadZipFile):
        return []
    return []


def _fallback_review(
    source_url: str,
    evidence: list[RepositoryFileEvidence],
    rule_evaluation: ProjectEvaluationResult | None,
) -> str:
    files = ", ".join(item.path for item in evidence[:20]) or "未读取到文本文件"
    score = f"规则评分：{rule_evaluation.overall_score}/100\n" if rule_evaluation else ""
    summary = rule_evaluation.summary if rule_evaluation else "已完成仓库只读工具检查。"
    return (
        f"仓库工具审查完成：{source_url}\n"
        f"{score}{summary}\n"
        f"已逐个读取文件：{files}\n"
        "当前模型未可用或调用失败，以上为工具读取结果与规则评价；"
        "请配置模型 API Key 后可获得 AI 深度代码评审。"
    )
