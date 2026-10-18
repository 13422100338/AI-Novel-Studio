from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

from ai_novel_studio.application.chapter_revision_service import ChapterRevisionService
from ai_novel_studio.application.compile_context_service import (
    CompiledContext,
    EvidenceNeed,
    EvidenceNeedKind,
)
from ai_novel_studio.core.context.token_budget import TokenBudget
from ai_novel_studio.harness.compile_step import (
    CompileChapterMissingError,
    CompileStepAdapter,
)
from ai_novel_studio.harness.run_engine import HarnessRunEngine
from ai_novel_studio.harness.run_state import HarnessRun, RunEventType, RunStage
from ai_novel_studio.infrastructure.storage.project_repository import ProjectRepository

_CONTENT = "第一段😀\r\n\r\n第二段证据\r\n"
_QUERY = "第二段证据"


def _project(tmp_path: Path):
    project = ProjectRepository.create(tmp_path / "novel", "B1 compile step")
    volume = project.list_volumes()[0]
    revisions = ChapterRevisionService(project)
    source = revisions.submit_creation(
        volume.id, "Evidence source", content=_CONTENT
    ).chapter
    target = revisions.submit_creation(
        volume.id, "Generation target", content="target"
    ).chapter
    return project, source, target


def _budget() -> TokenBudget:
    return TokenBudget(4096, 512, 128)


def _engine(
    project: ProjectRepository, **adapter_kwargs: object
) -> HarnessRunEngine:
    adapter = CompileStepAdapter.for_project(project, budget=_budget(), **adapter_kwargs)
    return HarnessRunEngine(project, compile_step=adapter)


def test_adapter_compiles_through_engine_port(tmp_path: Path) -> None:
    project, _source, target = _project(tmp_path)
    engine = _engine(project)
    run, _ = engine.start("写目标章", active_chapter_id=target.id)

    result = engine.compile_step(run.id)

    assert isinstance(result, CompiledContext)
    assert result.manifest.chapter_id == target.id
    assert result.manifest.run_id == run.id
    events = engine.store.replay(run.id)
    assert [event.event_type for event in events] == [
        RunEventType.RUN_CREATED,
        RunEventType.CONTEXT_COMPILATION_STARTED,
        RunEventType.CONTEXT_COMPILED,
    ]
    started, completed = events[1], events[2]
    assert started.payload == {"chapter_id": target.id}
    assert completed.payload == {
        "chapter_id": target.id,
        "manifest_id": result.manifest.id,
        "estimated_input_tokens": result.projection.estimated_input_tokens,
        "evidence_hit_count": 0,
        "included_categories": [
            list(item) for item in result.projection.included_categories
        ],
    }


def test_adapter_requires_active_chapter(tmp_path: Path) -> None:
    project, _source, _target = _project(tmp_path)
    engine = _engine(project)
    run, _ = engine.start("没有活动章节")

    with pytest.raises(CompileChapterMissingError):
        engine.compile_step(run.id)

    events = engine.store.replay(run.id)
    assert [event.event_type for event in events] == [RunEventType.RUN_CREATED]


def test_invalid_chapter_fails_before_any_compile_event(tmp_path: Path) -> None:
    project, _source, _target = _project(tmp_path)
    adapter = CompileStepAdapter.for_project(project, budget=_budget())
    now = datetime.now(UTC)
    run = HarnessRun(
        id="run-direct",
        goal="直接端口调用",
        stage=RunStage.CREATED,
        active_chapter_id="not-a-uuid",
        failure_code=None,
        failure_message=None,
        created_at=now,
        updated_at=now,
        completed_at=None,
    )

    with pytest.raises(ValueError):
        adapter(run)


def test_adapter_passes_evidence_requests_through(tmp_path: Path) -> None:
    project, source, target = _project(tmp_path)
    engine = _engine(
        project,
        evidence_requests=(EvidenceNeed(EvidenceNeedKind.EXACT_QUOTE, _QUERY),),
    )
    run, _ = engine.start("带证据编译", active_chapter_id=target.id)

    result = engine.compile_step(run.id)

    assert result.projection.evidence_hit_count == 1
    assert _CONTENT in result.projection.text
    assert len(result.manifest.retrieval_trace) == 1
    trace = result.manifest.retrieval_trace[0]
    assert trace.selected is True
    assert trace.chapter_id == source.id
    completed = engine.store.replay(run.id)[-1]
    assert completed.event_type is RunEventType.CONTEXT_COMPILED
    assert completed.payload["evidence_hit_count"] == 1
