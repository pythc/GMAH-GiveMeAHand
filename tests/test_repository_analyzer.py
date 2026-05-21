from pathlib import Path

import pytest

from agent_workflow.evaluation.repository import (
    RepositoryAnalysisError,
    RepositoryAnalyzer,
    normalize_github_url,
)


def test_normalize_github_url_rejects_non_github() -> None:
    with pytest.raises(RepositoryAnalysisError):
        normalize_github_url("https://example.com/a/b")


def test_repository_analyzer_summarizes_local_repository(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "README.md").write_text("# Demo\n实验 result Docker README", encoding="utf-8")
    (repo / "pyproject.toml").write_text("[project]\nname='demo'", encoding="utf-8")
    (repo / "src").mkdir()
    (repo / "src" / "main.py").write_text("print('ok')", encoding="utf-8")
    (repo / "tests").mkdir()
    (repo / "tests" / "test_main.py").write_text("def test_ok(): pass", encoding="utf-8")

    summary = RepositoryAnalyzer(root_dir=tmp_path / "work").summarize_path(
        repo,
        source_url="https://github.com/example/demo.git",
    )
    artifact = summary.to_artifact()

    assert summary.file_count == 4
    assert "README.md" in summary.important_files
    assert "tests/test_main.py" in summary.test_files
    assert artifact.kind == "code_repository"
    assert summary.tool_trace[0].startswith("工具：克隆仓库")
    assert "README.md" in "\n".join(summary.directory_tree)
    assert artifact.repository_summary is not None
    assert "智能体工具执行轨迹" in artifact.repository_summary
    assert "已读取文件内容" in artifact.repository_summary
