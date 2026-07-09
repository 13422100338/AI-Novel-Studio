import pytest

from ai_novel_studio.application.agent_tools import (
    AgentToolBudgetError,
    AgentToolRegistry,
    AgentToolRequest,
    AgentToolValidationError,
)
from ai_novel_studio.domain.agent import (
    AgentSourceRef,
    AgentToolName,
    AgentToolResult,
)


class EchoTool:
    name = AgentToolName.SEARCH_MEMORY
    required_arguments = ("query",)

    def execute(self, request: AgentToolRequest) -> AgentToolResult:
        return AgentToolResult(
            self.name,
            str(request.arguments["query"]) * 20,
            (AgentSourceRef("memory", "doc-1", 0, "abc"),),
            (),
            "hash",
        )


def test_registry_rejects_unknown_forbidden_and_missing_arguments() -> None:
    registry = AgentToolRegistry((EchoTool(),))

    with pytest.raises(AgentToolValidationError, match="unknown"):
        registry.execute("GET_UNKNOWN", {}, run_id="run", chapter_id=None, max_result_chars=10)

    with pytest.raises(AgentToolValidationError, match="forbidden"):
        registry.execute("WRITE_CHAPTER", {}, run_id="run", chapter_id=None, max_result_chars=10)

    with pytest.raises(AgentToolValidationError, match="query"):
        registry.execute(
            AgentToolName.SEARCH_MEMORY,
            {},
            run_id="run",
            chapter_id=None,
            max_result_chars=10,
        )


def test_registry_truncates_large_results_and_preserves_sources() -> None:
    registry = AgentToolRegistry((EchoTool(),))

    result = registry.execute(
        AgentToolName.SEARCH_MEMORY,
        {"query": "abcdef"},
        run_id="run",
        chapter_id=None,
        max_result_chars=12,
    )

    assert result.content == "abcdefabcdef"
    assert result.source_refs[0].source_id == "doc-1"
    assert result.omitted


def test_registry_rejects_invalid_budget() -> None:
    registry = AgentToolRegistry((EchoTool(),))

    with pytest.raises(AgentToolBudgetError):
        registry.execute(
            AgentToolName.SEARCH_MEMORY,
            {"query": "x"},
            run_id="run",
            chapter_id=None,
            max_result_chars=0,
        )
