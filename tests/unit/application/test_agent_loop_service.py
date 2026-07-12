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
