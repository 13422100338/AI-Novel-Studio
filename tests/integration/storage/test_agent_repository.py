from pathlib import Path

from ai_novel_studio.domain.agent import (
    AgentPurpose,
    AgentRunStatus,
    AgentToolCallStatus,
    AgentToolName,
    AgentTurnRole,
)
from ai_novel_studio.infrastructure.storage.agent_repository import AgentRepository
from ai_novel_studio.infrastructure.storage.chapter_repository import ChapterRepository
from ai_novel_studio.infrastructure.storage.project_repository import ProjectRepository


def _workspace(tmp_path: Path):  # type: ignore[no-untyped-def]
    project = ProjectRepository.create(tmp_path / "novel", "Agent Repository")
    chapter = ChapterRepository(project).create_chapter(
        project.list_volumes()[0].id,
        "Opening",
        "1",
        "hello",
    )
    return chapter, AgentRepository(project)


def test_agent_repository_persists_runs_turns_and_tool_calls(tmp_path: Path) -> None:
    chapter, agents = _workspace(tmp_path)
    run = agents.create_run(
        chapter_id=chapter.id,
        purpose=AgentPurpose.PLOT_DISCUSSION,
        status=AgentRunStatus.PREPARING,
        model_provider_id="provider",
        model_id="model",
        prompt_version="agent-v1",
        max_iterations=3,
        max_tool_calls=2,
        max_tool_result_chars=100,
    )

    user_turn = agents.add_turn(run.id, AgentTurnRole.USER, "question")
    tool_turn = agents.add_turn(run.id, AgentTurnRole.TOOL, "result", omitted=True)
    call = agents.add_tool_call(
        run.id,
        AgentToolName.SEARCH_MEMORY,
        '{"query":"letter"}',
        turn_id=user_turn.id,
    )
    completed_call = agents.complete_tool_call(
        call.id,
        AgentToolCallStatus.EXECUTED,
        '{"content":"result"}',
        6,
        '[{"source_type":"summary"}]',
    )
    completed_run = agents.update_run_status(run.id, AgentRunStatus.COMPLETED)

    assert completed_run.status == AgentRunStatus.COMPLETED
    assert agents.list_turns(run.id) == (user_turn, tool_turn)
    assert agents.list_tool_calls(run.id) == (completed_call,)
    assert user_turn.content_hash


def test_agent_repository_returns_latest_persisted_run(tmp_path: Path) -> None:
    chapter, agents = _workspace(tmp_path)
    assert agents.latest_run() is None

    first = agents.create_run(
        chapter_id=chapter.id,
        purpose=AgentPurpose.PLOT_DISCUSSION,
        status=AgentRunStatus.PREPARING,
        model_provider_id="provider",
        model_id="model",
        prompt_version="agent-v1",
        max_iterations=3,
        max_tool_calls=2,
        max_tool_result_chars=100,
    )
    second = agents.create_run(
        chapter_id=chapter.id,
        purpose=AgentPurpose.PLOT_DISCUSSION,
        status=AgentRunStatus.RUNNING,
        model_provider_id="provider",
        model_id="model",
        prompt_version="agent-v1",
        max_iterations=3,
        max_tool_calls=2,
        max_tool_result_chars=100,
    )

    assert first.id != second.id
    assert agents.latest_run() == second
