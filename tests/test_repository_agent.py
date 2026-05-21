from pathlib import Path
from typing import cast

from agent_workflow.evaluation.repository_agent import (
    AgenticRepositoryReviewer,
    RepositoryToolObservation,
)
from agent_workflow.llm.models import ChatCompletionRequest, ChatCompletionResult
from agent_workflow.llm.openai_compatible import OpenAICompatibleChatClient


class FakeToolLoopChatClient:
    api_key_configured = True

    def __init__(self) -> None:
        self.responses = [
            '{"tool":"clone_repository","arguments":{"url":"https://github.com/acme/demo"}}',
            '{"tool":"list_files","arguments":{"max_files":20}}',
            '{"tool":"read_file","arguments":{"path":"README.md"}}',
            '{"tool":"send_progress","arguments":{"message":"我正在阅读 README.md。"}}',
            '{"tool":"final_answer","arguments":{"message":"最终评价：README 已读取。"}}',
        ]
        self.requests: list[ChatCompletionRequest] = []

    def chat(self, request: ChatCompletionRequest) -> ChatCompletionResult:
        self.requests.append(request)
        return ChatCompletionResult(model="fake", content=self.responses.pop(0))


class LocalCloneReviewer(AgenticRepositoryReviewer):
    def __init__(self, source: Path, *, root_dir: Path, max_tool_calls: int) -> None:
        super().__init__(root_dir=root_dir, max_tool_calls=max_tool_calls)
        self.source = source

    def _clone(
        self,
        clone_url: str,
        destination: Path,
        observations: list[RepositoryToolObservation],
    ) -> None:
        destination.mkdir(parents=True)
        (destination / "README.md").write_text(
            (self.source / "README.md").read_text(encoding="utf-8"),
            encoding="utf-8",
        )
        observations.append(
            RepositoryToolObservation(
                tool="clone_repository",
                input={"url": clone_url, "depth": 1},
                output="success",
            )
        )


def test_agentic_repository_reviewer_reads_files_without_model(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "README.md").write_text("# Demo\n实验结果和复现说明", encoding="utf-8")
    (repo / "src").mkdir()
    (repo / "src" / "main.py").write_text("def main():\n    return 'ok'", encoding="utf-8")

    reviewer = AgenticRepositoryReviewer(root_dir=tmp_path / "work", max_inspected_files=10)
    observations: list[RepositoryToolObservation] = []
    files = ["README.md", "src/main.py"]
    evidence = reviewer._read_selected_files(repo, files, observations)  # noqa: SLF001

    assert [item.path for item in evidence] == files
    assert observations[0].tool == "read_file"
    assert "def main" in evidence[1].content


def test_agentic_repository_reviewer_runs_model_tool_loop(tmp_path: Path) -> None:
    source = tmp_path / "source"
    source.mkdir()
    (source / "README.md").write_text("# Demo\n可复现说明", encoding="utf-8")
    progress_messages: list[str] = []
    fake_client = FakeToolLoopChatClient()
    reviewer = LocalCloneReviewer(
        source,
        root_dir=tmp_path / "work",
        max_tool_calls=8,
    )

    review = reviewer.review_url(
        "https://github.com/acme/demo",
        topic_title="测试课题",
        topic_goal="验证工具循环",
        chat_client=cast(OpenAICompatibleChatClient, fake_client),
        agent_system_prompt="你是测试智能体。",
        progress_callback=progress_messages.append,
    )

    assert progress_messages == ["我正在阅读 README.md。"]
    assert review.final_review == "最终评价：README 已读取。"
    assert review.inspected_files == ["README.md"]
    assert [item.tool for item in review.observations] == [
        "clone_repository",
        "list_files",
        "read_file",
        "send_progress",
        "cleanup_workspace",
    ]
