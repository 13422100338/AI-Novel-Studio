from pathlib import Path

from ai_novel_studio.application.agent_loop_service import (
    AgentLoopRequest,
    AgentLoopService,
)
from ai_novel_studio.application.agent_tools import AgentToolRegistry, AgentToolRequest
from ai_novel_studio.domain.agent import (
    AgentPurpose,
    AgentRunStatus,
    AgentSourceRef,
    AgentToolCallStatus,
    AgentToolName,
    AgentToolResult,
)
from ai_novel_studio.infrastructure.llm import LLMMessage
from ai_novel_studio.infrastructure.storage.agent_repository import AgentRepository
from ai_novel_studio.infrastructure.storage.project_repository import ProjectRepository


class EchoTool:
    name = AgentToolName.SEARCH_MEMORY
    required_arguments = ("query",)

    def execute(self, request: AgentToolRequest) -> AgentToolResult:
        return AgentToolResult(
            self.name,
            f"evidence:{request.arguments['query']}",
            (AgentSourceRef("memory", "doc-1", 0, "hash"),),
            (),
            "result-hash",
        )


class ListChaptersTool:
    name = AgentToolName.LIST_CHAPTERS
    required_arguments: tuple[str, ...] = ()

    def execute(self, request: AgentToolRequest) -> AgentToolResult:
        return AgentToolResult(
            self.name,
            "chapter_id=chapter-2 | 第二章",
            (),
            (),
            "list-hash",
        )


class ReadChapterTool:
    name = AgentToolName.READ_CHAPTER_EXCERPT
    required_arguments = ("chapter_id",)

    def execute(self, request: AgentToolRequest) -> AgentToolResult:
        return AgentToolResult(
            self.name,
            "第二章正文证据",
            (),
            (),
            "read-hash",
        )


class ReadChaptersBatchTool:
    name = AgentToolName.READ_CHAPTERS_BATCH
    required_arguments = ("chapter_ids",)

    def execute(self, request: AgentToolRequest) -> AgentToolResult:
        return AgentToolResult(
            self.name,
            "第一章与第二章的批量证据",
            (),
            (),
            "batch-hash",
        )


class FakeModel:
    def __init__(self, replies: list[dict[str, object]]) -> None:
        self.replies = replies
        self.messages: list[tuple[LLMMessage, ...]] = []

    def complete_json(
        self,
        messages: tuple[LLMMessage, ...],
        *,
        output_token_limit: int,
    ) -> dict[str, object]:
        self.messages.append(messages)
        return self.replies.pop(0)


def _service(tmp_path: Path, model: FakeModel) -> tuple[AgentLoopService, AgentRepository]:
    project = ProjectRepository.create(tmp_path / "novel", "Agent Loop")
    repository = AgentRepository(project)
    service = AgentLoopService(repository, AgentToolRegistry((EchoTool(),)), model)
    return service, repository


def test_agent_loop_executes_tool_then_final_answer(tmp_path: Path) -> None:
    model = FakeModel(
        [
            {
                "action": "tool",
                "tool_calls": [
                    {"tool_name": "SEARCH_MEMORY", "arguments": {"query": "old letter"}}
                ],
            },
            {"action": "final", "final_answer": "根据证据，旧信应在本章回收。"},
        ]
    )
    service, repository = _service(tmp_path, model)

    result = service.run(
        AgentLoopRequest(
            chapter_id=None,
            purpose=AgentPurpose.PLOT_DISCUSSION,
            messages=(LLMMessage("system", "boundary"), LLMMessage("user", "question")),
            model_provider_id="provider",
            model_id="model",
            prompt_version="agent-v1",
            max_iterations=3,
            max_tool_calls=2,
            max_tool_result_chars=40,
            output_token_limit=100,
        )
    )

    assert result.status == AgentRunStatus.COMPLETED
    assert result.final_answer == "根据证据，旧信应在本章回收。"
    assert repository.list_tool_calls(result.run_id)[0].status == AgentToolCallStatus.EXECUTED
    assert any(
        "evidence:old letter" in turn.content
        for turn in repository.list_turns(result.run_id)
    )


def test_agent_loop_requires_tool_before_final_when_retrieval_is_enabled(
    tmp_path: Path,
) -> None:
    model = FakeModel(
        [
            {"action": "final", "final_answer": "没有上下文。"},
            {
                "action": "tool",
                "tool_calls": [
                    {"tool_name": "SEARCH_MEMORY", "arguments": {"query": "过往经历"}}
                ],
            },
            {"action": "final", "final_answer": "根据检索到的前文给出建议。"},
        ]
    )
    service, repository = _service(tmp_path, model)

    result = service.run(
        AgentLoopRequest(
            chapter_id=None,
            purpose=AgentPurpose.PLOT_DISCUSSION,
            messages=(LLMMessage("user", "请参考前文"),),
            model_provider_id="provider",
            model_id="model",
            prompt_version="agent-v1",
            max_iterations=4,
            max_tool_calls=2,
            max_tool_result_chars=200,
            output_token_limit=100,
            require_tool_before_final=True,
        )
    )

    assert result.status == AgentRunStatus.COMPLETED
    assert len(repository.list_tool_calls(result.run_id)) == 1
    assert any(
        "必须先调用至少一个只读工具" in message.content
        for message in model.messages[1]
    )
    assert any(
        message.role == "user" and "未信任证据" in message.content
        for message in model.messages[2]
    )


def test_agent_loop_requires_each_named_cross_chapter_tool(tmp_path: Path) -> None:
    model = FakeModel(
        [
            {"action": "final", "final_answer": "我只能看当前章。"},
            {
                "action": "tool",
                "tool_calls": [
                    {"tool_name": "LIST_CHAPTERS", "arguments": {}},
                    {
                        "tool_name": "READ_CHAPTERS_BATCH",
                        "arguments": {"chapter_ids": ["chapter-2"]},
                    },
                ],
            },
            {"action": "final", "final_answer": "根据第二章证据给出全书分析。"},
        ]
    )
    project = ProjectRepository.create(tmp_path / "novel", "Agent Loop")
    repository = AgentRepository(project)
    service = AgentLoopService(
        repository,
        AgentToolRegistry((ListChaptersTool(), ReadChaptersBatchTool())),
        model,
    )

    result = service.run(
        AgentLoopRequest(
            chapter_id=None,
            purpose=AgentPurpose.PLOT_DISCUSSION,
            messages=(LLMMessage("user", "概括整本小说"),),
            model_provider_id="provider",
            model_id="model",
            prompt_version="agent-v1",
            max_iterations=3,
            max_tool_calls=2,
            max_tool_result_chars=200,
            output_token_limit=100,
            required_tool_names=(
                AgentToolName.LIST_CHAPTERS,
                AgentToolName.READ_CHAPTERS_BATCH,
            ),
        )
    )

    assert result.status is AgentRunStatus.COMPLETED
    assert result.final_answer == "根据第二章证据给出全书分析。"
    assert [call.tool_name for call in repository.list_tool_calls(result.run_id)] == [
        AgentToolName.LIST_CHAPTERS,
        AgentToolName.READ_CHAPTERS_BATCH,
    ]
    assert any(
        "LIST_CHAPTERS" in message.content
        and "READ_CHAPTERS_BATCH" in message.content
        for message in model.messages[1]
    )


def test_agent_loop_does_not_spend_tool_budget_on_identical_directory_call(
    tmp_path: Path,
) -> None:
    model = FakeModel(
        [
            {
                "action": "tool",
                "tool_calls": [{"tool_name": "LIST_CHAPTERS", "arguments": {}}],
            },
            {
                "action": "tool",
                "tool_calls": [{"tool_name": "LIST_CHAPTERS", "arguments": {}}],
            },
            {
                "action": "tool",
                "tool_calls": [
                    {
                        "tool_name": "READ_CHAPTERS_BATCH",
                        "arguments": {"chapter_ids": ["chapter-2"]},
                    }
                ],
            },
            {"action": "final", "final_answer": "跨章回答。"},
        ]
    )
    project = ProjectRepository.create(tmp_path / "novel", "Agent Loop")
    repository = AgentRepository(project)
    service = AgentLoopService(
        repository,
        AgentToolRegistry((ListChaptersTool(), ReadChaptersBatchTool())),
        model,
    )

    result = service.run(
        AgentLoopRequest(
            chapter_id=None,
            purpose=AgentPurpose.PLOT_DISCUSSION,
            messages=(LLMMessage("user", "整本小说"),),
            model_provider_id="provider",
            model_id="model",
            prompt_version="agent-v3",
            max_iterations=4,
            max_tool_calls=2,
            max_tool_result_chars=200,
            output_token_limit=100,
            required_tool_names=(
                AgentToolName.LIST_CHAPTERS,
                AgentToolName.READ_CHAPTERS_BATCH,
            ),
        )
    )

    assert result.status is AgentRunStatus.COMPLETED
    assert [call.tool_name for call in repository.list_tool_calls(result.run_id)] == [
        AgentToolName.LIST_CHAPTERS,
        AgentToolName.READ_CHAPTERS_BATCH,
    ]
    assert any(
        "不要重复调用相同的 LIST_CHAPTERS" in message.content
        for message in model.messages[2]
    )


def test_agent_loop_retries_invalid_json_then_accepts_valid_answer(
    tmp_path: Path,
) -> None:
    class CorrectingModel:
        def __init__(self) -> None:
            self.calls = 0
            self.messages: list[tuple[LLMMessage, ...]] = []

        def complete_json(
            self,
            messages: tuple[LLMMessage, ...],
            *,
            output_token_limit: int,
        ) -> dict[str, object]:
            self.calls += 1
            self.messages.append(messages)
            if self.calls == 1:
                raise ValueError("raw malformed provider payload")
            return {"action": "final", "final_answer": "格式修正后的回答"}

    model = CorrectingModel()
    service, _repository = _service(tmp_path, model)  # type: ignore[arg-type]

    result = service.run(
        AgentLoopRequest(
            chapter_id=None,
            purpose=AgentPurpose.PLOT_DISCUSSION,
            messages=(LLMMessage("user", "继续讨论"),),
            model_provider_id="provider",
            model_id="model",
            prompt_version="agent-v1",
            max_iterations=2,
            output_token_limit=100,
        )
    )

    assert result.status is AgentRunStatus.COMPLETED
    assert result.final_answer == "格式修正后的回答"
    assert model.calls == 2
    assert "有效 JSON" in model.messages[1][-1].content
    assert "raw malformed provider payload" not in model.messages[1][-1].content


def test_agent_loop_rejects_forbidden_tool_and_records_failure(tmp_path: Path) -> None:
    model = FakeModel(
        [{"action": "tool", "tool_calls": [{"tool_name": "WRITE_CHAPTER", "arguments": {}}]}]
    )
    service, repository = _service(tmp_path, model)

    result = service.run(
        AgentLoopRequest(
            chapter_id=None,
            purpose=AgentPurpose.PLOT_DISCUSSION,
            messages=(LLMMessage("user", "question"),),
            model_provider_id="provider",
            model_id="model",
            prompt_version="agent-v1",
            max_iterations=1,
            max_tool_calls=1,
            max_tool_result_chars=40,
            output_token_limit=100,
        )
    )

    assert result.status == AgentRunStatus.FAILED
    assert repository.list_tool_calls(result.run_id)[0].status == AgentToolCallStatus.REJECTED


def test_agent_loop_stops_runaway_iterations(tmp_path: Path) -> None:
    model = FakeModel(
        [
            {
                "action": "tool",
                "tool_calls": [
                    {"tool_name": "SEARCH_MEMORY", "arguments": {"query": "loop"}}
                ],
            },
            {
                "action": "tool",
                "tool_calls": [
                    {"tool_name": "SEARCH_MEMORY", "arguments": {"query": "loop"}}
                ],
            },
        ]
    )
    service, _ = _service(tmp_path, model)

    result = service.run(
        AgentLoopRequest(
            chapter_id=None,
            purpose=AgentPurpose.PLOT_DISCUSSION,
            messages=(LLMMessage("user", "question"),),
            model_provider_id="provider",
            model_id="model",
            prompt_version="agent-v1",
            max_iterations=1,
            max_tool_calls=2,
            max_tool_result_chars=40,
            output_token_limit=100,
        )
    )

    assert result.status == AgentRunStatus.FAILED
    assert result.failure_code == "MAX_ITERATIONS"
