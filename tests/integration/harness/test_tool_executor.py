from __future__ import annotations

from pathlib import Path

import pytest

from ai_novel_studio.core.context.token_budget import TokenBudget
from ai_novel_studio.harness.approval_repository import ApprovalRepository
from ai_novel_studio.harness.core_tools import TOOL_MANUSCRIPT_READ, CoreToolService
from ai_novel_studio.harness.event_repository import HarnessEventRepository
from ai_novel_studio.harness.event_store import HarnessEventStore
from ai_novel_studio.harness.permission_gateway import PermissionGateway
from ai_novel_studio.harness.run_state import RunEventType, RunStage
from ai_novel_studio.harness.subject_tools import (
    TOOL_SUBJECT_PROPOSE_MERGE,
    SubjectToolService,
)
from ai_novel_studio.harness.tool_executor import (
    ToolCallDeniedError,
    ToolCallRequiresApprovalError,
    ToolExecutor,
)
from ai_novel_studio.harness.tool_registry import (
    ToolDefinition,
    ToolRegistry,
    ToolRiskLevel,
    ToolScope,
    WriteEffect,
)
from ai_novel_studio.infrastructure.storage.character_memory_repository import (
    CharacterMemoryRepository,
)
from ai_novel_studio.infrastructure.storage.project_repository import ProjectRepository


def _executor(tmp_path: Path):
    project = ProjectRepository.create(tmp_path / "novel", "Tool executor")
    store = HarnessEventStore(HarnessEventRepository(project))
    registry = ToolRegistry()
    from ai_novel_studio.harness.core_tools import register_core_tools
    from ai_novel_studio.harness.subject_tools import register_subject_tools

    register_core_tools(registry)
    register_subject_tools(registry)
    core = CoreToolService.for_project(
        project, budget=TokenBudget(4096, 512, 128), registry=registry
    )
    subjects = SubjectToolService.for_project(project)
    run, _ = store.start_run(goal="闸门执行", active_chapter_id=None)
    return (
        project,
        store,
        run,
        ToolExecutor(store, PermissionGateway(registry), core, subjects),
        core,
        subjects,
    )


def _tool_events(store: HarnessEventStore, run_id: str) -> list[RunEventType]:
    return [
        event.event_type
        for event in store.replay(run_id)
        if event.event_type.value.startswith("TOOL_CALL")
    ]


def test_allowed_call_executes_and_records_started_completed(tmp_path: Path) -> None:
    project, store, run, executor, _core, _subjects = _executor(tmp_path)
    volume = project.list_volumes()[0]
    from ai_novel_studio.application.chapter_revision_service import (
        ChapterRevisionService,
    )

    chapter = ChapterRevisionService(project).submit_creation(
        volume.id, "Chapter", content="正文"
    ).chapter

    execution = executor.execute(
        run.id, TOOL_MANUSCRIPT_READ, {"chapter_id": chapter.id}
    )

    assert execution.decision.value == "ALLOWED"
    assert "正文" in execution.result.content  # type: ignore[union-attr]
    assert _tool_events(store, run.id) == [
        RunEventType.TOOL_CALL_STARTED,
        RunEventType.TOOL_CALL_COMPLETED,
    ]


def test_proposal_tool_without_key_is_denied_with_failed_event(
    tmp_path: Path,
) -> None:
    _project, store, run, executor, _core, _subjects = _executor(tmp_path)
    memory = CharacterMemoryRepository(_project)
    source = memory.create_character("艾瑞克")
    target = memory.create_character("艾瑞克·温德米尔")

    with pytest.raises(ToolCallDeniedError):
        executor.execute(
            run.id,
            TOOL_SUBJECT_PROPOSE_MERGE,
            {
                "source_subject_id": source.id,
                "target_subject_id": target.id,
                "reason": "同一人物",
            },
        )

    assert _tool_events(store, run.id) == [RunEventType.TOOL_CALL_FAILED]
    assert ApprovalRepository(_project).list_for_run(run.id) == ()


def test_proposal_tool_with_key_executes(tmp_path: Path) -> None:
    project, store, run, executor, _core, _subjects = _executor(tmp_path)
    memory = CharacterMemoryRepository(project)
    source = memory.create_character("艾瑞克")
    target = memory.create_character("艾瑞克·温德米尔")

    execution = executor.execute(
        run.id,
        TOOL_SUBJECT_PROPOSE_MERGE,
        {
            "source_subject_id": source.id,
            "target_subject_id": target.id,
            "reason": "同一人物",
            "idempotency_key": "sm-1",
        },
        idempotency_key="sm-1",
    )

    assert execution.decision.value == "ALLOWED"
    assert ApprovalRepository(project).get_by_key(run.id, "sm-1") is not None


def test_formal_write_never_executes(tmp_path: Path) -> None:
    _project, store, run, _executor_unused, core, subjects = _executor(tmp_path)
    registry = ToolRegistry()
    registry.register(
        ToolDefinition(
            "knowledge.commit",
            1,
            ToolScope.PROJECT,
            ToolRiskLevel.PROPOSAL,
            WriteEffect.FORMAL_WRITE,
            False,
            {"type": "object"},
            {"type": "object"},
        )
    )
    gated = ToolExecutor(store, PermissionGateway(registry), core, subjects)

    with pytest.raises(ToolCallRequiresApprovalError):
        gated.execute(
            run.id,
            "knowledge.commit",
            {},
            expected_revision=1,
            idempotency_key="k-1",
        )

    assert RunEventType.TOOL_CALL_STARTED not in _tool_events(store, run.id)
    assert RunEventType.TOOL_CALL_FAILED in _tool_events(store, run.id)


def test_closed_run_is_denied_before_any_dispatch(tmp_path: Path) -> None:
    _project, store, run, executor, _core, _subjects = _executor(tmp_path)
    store.transition(run.id, RunStage.CANCELLED)

    with pytest.raises(ToolCallDeniedError):
        executor.execute(run.id, TOOL_MANUSCRIPT_READ, {"chapter_id": "x"})

    assert _tool_events(store, run.id) == []


def test_unknown_tool_is_denied(tmp_path: Path) -> None:
    _project, store, run, executor, _core, _subjects = _executor(tmp_path)

    with pytest.raises(ToolCallDeniedError):
        executor.execute(run.id, "no.such_tool", {})

    assert _tool_events(store, run.id) == [RunEventType.TOOL_CALL_FAILED]


def test_failed_dispatch_records_failed_event(tmp_path: Path) -> None:
    _project, store, run, executor, _core, _subjects = _executor(tmp_path)

    with pytest.raises(ValueError):
        executor.execute(run.id, TOOL_MANUSCRIPT_READ, {"chapter_id": "not-a-uuid"})

    assert _tool_events(store, run.id) == [
        RunEventType.TOOL_CALL_STARTED,
        RunEventType.TOOL_CALL_FAILED,
    ]
