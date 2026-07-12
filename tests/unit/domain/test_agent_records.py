from dataclasses import FrozenInstanceError
from datetime import UTC, datetime

import pytest

from ai_novel_studio.domain.agent import (
    AgentPurpose,
    AgentRun,
    AgentRunStatus,
    AgentSourceRef,
    AgentToolCallStatus,
    AgentToolName,
    AgentToolResult,
    AgentTurnRole,
)


def test_agent_enums_have_stable_values() -> None:
    assert AgentPurpose.PLOT_DISCUSSION.value == "PLOT_DISCUSSION"
    assert AgentRunStatus.WAITING_FOR_TOOL.value == "WAITING_FOR_TOOL"
    assert AgentTurnRole.TOOL.value == "TOOL"
    assert AgentToolName.SEARCH_MEMORY.value == "SEARCH_MEMORY"
    assert AgentToolCallStatus.REJECTED.value == "REJECTED"


def test_agent_run_validates_required_ids_and_budgets() -> None:
    now = datetime.now(UTC)

    with pytest.raises(ValueError, match="id"):
        AgentRun(
            "",
            None,
            AgentPurpose.PLOT_DISCUSSION,
            AgentRunStatus.PREPARING,
            "provider",
            "model",
            "prompt-v1",
            1,
            0,
            1,
            0,
            0,
            None,
            None,
            None,
            None,
            None,
            None,
            now,
            now,
            None,
        )

    with pytest.raises(ValueError, match="max_iterations"):
        AgentRun(
            "run-1",
            None,
            AgentPurpose.PLOT_DISCUSSION,
            AgentRunStatus.PREPARING,
            "provider",
            "model",
            "prompt-v1",
            0,
            0,
            1,
            0,
            0,
            None,
            None,
            None,
            None,
            None,
            None,
            now,
            now,
            None,
        )


def test_agent_source_ref_and_tool_result_are_immutable_and_hashed() -> None:
    ref = AgentSourceRef("chapter", "chapter-1", 0, "abc123")
    result = AgentToolResult(
        AgentToolName.READ_CHAPTER_EXCERPT,
        "excerpt",
        (ref,),
        ("truncated",),
        "result-hash",
    )

    assert result.source_refs == (ref,)
    with pytest.raises(FrozenInstanceError):
        result.content = "changed"  # type: ignore[misc]

    with pytest.raises(ValueError, match="source_hash"):
        AgentSourceRef("chapter", "chapter-1", 0, "")
