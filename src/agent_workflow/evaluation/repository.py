"""Safe repository summarization for project evaluation."""

import hashlib
import os
import subprocess
import tempfile
from pathlib import Path
from urllib.parse import urlparse

from pydantic import BaseModel, Field

from agent_workflow.evaluation.models import ArtifactInput, ArtifactKind

_DEFAULT_ROOT = Path("data/repository-workspaces")
_ALLOWED_HOSTS = {"github.com", "www.github.com"}
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
}
_IMPORTANT_NAMES = {
    "readme.md",
    "readme.rst",
    "readme.txt",
    "pyproject.toml",
    "package.json",
    "requirements.txt",
    "dockerfile",
    "docker-compose.yml",
    "compose.yml",
    "makefile",
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
    ".go",
    ".java",
    ".rs",
}


class RepositoryAnalysisError(RuntimeError):
    """Raised when a repository cannot be safely analyzed."""


class RepositorySummary(BaseModel):
    source_url: str
    local_path: str | None = None
    file_count: int
    important_files: list[str] = Field(default_factory=list)
    code_files: list[str] = Field(default_factory=list)
    test_files: list[str] = Field(default_factory=list)
    ci_files: list[str] = Field(default_factory=list)
    directory_tree: list[str] = Field(default_factory=list)
    tool_trace: list[str] = Field(default_factory=list)
    text_preview: str

    def to_artifact(self) -> ArtifactInput:
        return ArtifactInput(
            artifact_id="github-repository",
            kind=ArtifactKind.CODE_REPOSITORY,
            title="GitHub 代码仓库",
            uri=self.source_url,
            repository_summary=self.to_review_text(),
            metadata={
                "local_path": self.local_path,
                "file_count": self.file_count,
                "important_files": self.important_files,
                "test_files": self.test_files,
                "ci_files": self.ci_files,
                "directory_tree": self.directory_tree,
                "tool_trace": self.tool_trace,
            },
        )

    def to_review_text(self) -> str:
        return "\n".join(
            [
                f"仓库地址：{self.source_url}",
                f"文件总数：{self.file_count}",
                "重要文件：" + ", ".join(self.important_files[:30]),
                "测试文件：" + ", ".join(self.test_files[:30]),
                "CI 文件：" + ", ".join(self.ci_files[:20]),
                "核心代码文件：" + ", ".join(self.code_files[:50]),
                "智能体工具执行轨迹：\n" + "\n".join(self.tool_trace),
                "目录结构节选：\n" + "\n".join(self.directory_tree[:120]),
                "已读取文件内容：",
                self.text_preview,
            ]
        )


class RepositoryAnalyzer:
    """Clone and summarize allowed public repositories without executing project code."""

    def __init__(
        self,
        *,
        root_dir: Path = _DEFAULT_ROOT,
        clone_timeout_seconds: int = 60,
        max_files: int = 600,
        max_preview_chars: int = 60_000,
        max_file_chars: int = 8_000,
    ) -> None:
        self.root_dir = root_dir
        self.clone_timeout_seconds = clone_timeout_seconds
        self.max_files = max_files
        self.max_preview_chars = max_preview_chars
        self.max_file_chars = max_file_chars

    def analyze_url(self, url: str) -> RepositorySummary:
        clone_url, repo_key = normalize_github_url(url)
        self.root_dir.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix=f"{repo_key}-", dir=self.root_dir) as workspace:
            destination = Path(workspace) / "repo"
            try:
                subprocess.run(
                    ["git", "clone", "--depth", "1", clone_url, str(destination)],
                    check=True,
                    timeout=self.clone_timeout_seconds,
                    capture_output=True,
                    text=True,
                    env={**os.environ, "GIT_TERMINAL_PROMPT": "0"},
                )
            except FileNotFoundError as exc:
                message = "git is required to analyze repository links"
                raise RepositoryAnalysisError(message) from exc
            except subprocess.TimeoutExpired as exc:
                raise RepositoryAnalysisError("repository clone timed out") from exc
            except subprocess.CalledProcessError as exc:
                detail = (exc.stderr or exc.stdout or "git clone failed").strip()
                raise RepositoryAnalysisError(detail[-500:]) from exc
            summary = self.summarize_path(destination, source_url=clone_url)
            return summary.model_copy(update={"local_path": None})

    def summarize_path(self, path: Path, *, source_url: str) -> RepositorySummary:
        if not path.exists() or not path.is_dir():
            raise RepositoryAnalysisError(f"repository path does not exist: {path}")
        files = _safe_files(path, max_files=self.max_files)
        important = _important_files(path, files)
        code_files = [item for item in files if Path(item).suffix.lower() in _TEXT_SUFFIXES]
        test_files = [item for item in files if "test" in item.lower() or "spec" in item.lower()]
        ci_files = [item for item in files if item.startswith(".github/") or "/ci" in item.lower()]
        selected_files = important + code_files[:20]
        preview = _build_preview(
            path,
            selected_files,
            max_preview_chars=self.max_preview_chars,
            max_file_chars=self.max_file_chars,
        )
        directory_tree = _directory_tree(files)
        tool_trace = _tool_trace(
            source_url=source_url,
            file_count=len(files),
            selected_files=selected_files,
            test_files=test_files,
            ci_files=ci_files,
        )
        return RepositorySummary(
            source_url=source_url,
            local_path=str(path),
            file_count=len(files),
            important_files=important,
            code_files=code_files,
            test_files=test_files,
            ci_files=ci_files,
            directory_tree=directory_tree,
            tool_trace=tool_trace,
            text_preview=preview,
        )


def normalize_github_url(url: str) -> tuple[str, str]:
    parsed = urlparse(url.strip())
    if parsed.scheme not in {"http", "https"} or parsed.hostname not in _ALLOWED_HOSTS:
        raise RepositoryAnalysisError("only GitHub http(s) repository links are supported")
    parts = [part for part in parsed.path.strip("/").split("/") if part]
    if len(parts) < 2:
        raise RepositoryAnalysisError("GitHub URL must include owner and repository")
    owner = _safe_part(parts[0])
    repo = _safe_part(parts[1].removesuffix(".git"))
    clone_url = f"https://github.com/{owner}/{repo}.git"
    digest = hashlib.sha256(clone_url.encode()).hexdigest()[:12]
    return clone_url, f"{owner}-{repo}-{digest}"


def _safe_part(value: str) -> str:
    safe = "".join(ch for ch in value if ch.isalnum() or ch in {"-", "_", "."})
    if not safe or safe in {".", ".."}:
        raise RepositoryAnalysisError("invalid GitHub URL path")
    return safe[:80]


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


def _important_files(root: Path, files: list[str]) -> list[str]:
    important = []
    for item in files:
        lower = Path(item).name.lower()
        if lower in _IMPORTANT_NAMES or item.startswith(".github/workflows/"):
            important.append(item)
    if not important:
        important = files[:20]
    return important


def _directory_tree(files: list[str], *, limit: int = 160) -> list[str]:
    tree: list[str] = []
    for item in files[:limit]:
        depth = max(0, len(Path(item).parts) - 1)
        tree.append(f"{'  ' * depth}- {Path(item).name if depth else item}")
    if len(files) > limit:
        tree.append(f"... 其余 {len(files) - limit} 个文件已省略")
    return tree


def _tool_trace(
    *,
    source_url: str,
    file_count: int,
    selected_files: list[str],
    test_files: list[str],
    ci_files: list[str],
) -> list[str]:
    return [
        f"工具：克隆仓库；地址：{source_url}；深度：1",
        f"工具：列出文件；结果：共 {file_count} 个文件",
        "工具：查找测试文件；结果：" + (", ".join(test_files[:20]) or "未发现"),
        "工具：查找持续集成配置；结果：" + (", ".join(ci_files[:20]) or "未发现"),
        "工具：读取文件；结果：" + ", ".join(dict.fromkeys(selected_files[:40])),
        "工具：清理临时工作区；结果：临时源码目录已清理",
    ]


def _build_preview(
    root: Path,
    files: list[str],
    *,
    max_preview_chars: int,
    max_file_chars: int,
) -> str:
    chunks: list[str] = []
    seen: set[str] = set()
    current = 0
    for rel in files:
        suffix = Path(rel).suffix.lower()
        name = Path(rel).name.lower()
        if rel in seen or (suffix not in _TEXT_SUFFIXES and name not in _IMPORTANT_NAMES):
            continue
        seen.add(rel)
        path = root / rel
        try:
            text = path.read_text(encoding="utf-8", errors="ignore")[:max_file_chars]
        except OSError:
            continue
        chunk = f"\n--- {rel} ---\n{text}"
        if current + len(chunk) > max_preview_chars:
            break
        chunks.append(chunk)
        current += len(chunk)
    return "\n".join(chunks).strip()
