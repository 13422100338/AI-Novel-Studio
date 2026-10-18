from __future__ import annotations

import hashlib
from dataclasses import fields
from datetime import UTC, datetime
from pathlib import Path

import pytest

from ai_novel_studio.application.shared_semantic_import_service import (
    SharedSemanticChapterResult,
    SharedSemanticImportFailure,
    SharedSemanticImportFailureCode,
    SharedSemanticImportReport,
)
from ai_novel_studio.application.shared_semantic_occurrence_batch_service import (
    OccurrenceImportBindingReport,
    SharedSemanticOccurrenceBatchService,
)
from ai_novel_studio.application.shared_semantic_occurrence_service import (
    OccurrenceBindingFailureCode,
    OccurrenceBindingStatus,
    SharedSemanticOccurrenceService,
)
from ai_novel_studio.core.context.semantic_windowing import (
    SemanticWindow,
    project_semantic_windows,
)
from ai_novel_studio.core.context.shared_semantic_result import (
    OccurrenceCandidate,
    SharedSemanticResult,
    SourceSpan,
    candidate_source_id,
)
from ai_novel_studio.infrastructure.storage.chapter_repository import ChapterRepository
from ai_novel_studio.infrastructure.storage.character_memory_repository import (
    CharacterMemoryRepository,
)
from ai_novel_studio.infrastructure.storage.occurrence_repository import (
    OccurrenceRepository,
)
from ai_novel_studio.infrastructure.storage.project_repository import ProjectRepository

_NOW = datetime(2026, 8, 22, 8, 0, tzinfo=UTC)


def _hash(content: str) -> str:
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


def _project(tmp_path: Path) -> ProjectRepository:
    return ProjectRepository.create(tmp_path / "project", "Occurrence batch")


def _add_chapter(
    project: ProjectRepository,
    title: str,
    content: str,
) -> tuple[str, int, str]:
    chapter = ChapterRepository(project).create_chapter(
        project.list_volumes()[0].id,
        title,
        content=content,
    )
    return chapter.id, chapter.revision, _hash(content)


def _windows(
    project: ProjectRepository,
    chapter_id: str,
    revision: int,
    source_hash: str,
    narrative_sequence: int,
    content: str,
) -> tuple[SemanticWindow, ...]:
    return project_semantic_windows(
        chapter_id,
        revision,
        source_hash,
        narrative_sequence,
        content,
    )


def _result(window: SemanticWindow) -> SharedSemanticResult:
    span = SourceSpan(0, 1, window.text[0:1])
    return SharedSemanticResult(
        window=window,
        subject_mentions=(),
        aliases=(),
        occurrences=(
            OccurrenceCandidate(
                candidate_source_id(window, "occurrence", 0),
                "DISCOVERY",
                f"Event {window.window_ordinal}",
                f"Event summary {window.window_ordinal}",
                (span,),
            ),
        ),
        participant_links=(),
        state_changes=(),
        view_differences=(),
        summary=None,
    )


def _chapter(
    project: ProjectRepository,
    chapter_id: str,
    revision: int,
    source_hash: str,
    narrative_sequence: int,
    content: str,
) -> SharedSemanticChapterResult:
    windows = _windows(
        project,
        chapter_id,
        revision,
        source_hash,
        narrative_sequence,
        content,
    )
    return SharedSemanticChapterResult(
        chapter_id=chapter_id,
        source_revision=revision,
        source_hash=source_hash,
        narrative_sequence=narrative_sequence,
        results=tuple(_result(window) for window in windows),
    )


def _analysis_failure(chapter_title: str = "缺失章") -> SharedSemanticImportFailure:
    return SharedSemanticImportFailure(
        "00000000-0000-0000-0000-00000000000a",
        chapter_title,
        SharedSemanticImportFailureCode.ANALYSIS_FAILED,
        "shared semantic analysis failed",
    )


def test_binds_every_analyzed_chapter_once_in_report_order(tmp_path: Path) -> None:
    project = _project(tmp_path)
    CharacterMemoryRepository(project).create_character("艾")
    identities = [
        _add_chapter(project, f"第{index}章", f"艾琳行动{index}。")
        for index in range(3)
    ]
    chapters = tuple(
        _chapter(project, *identity, index + 1, content)
        for index, (identity, content) in enumerate(
            zip(
                identities,
                (f"艾琳行动{index}。" for index in range(3)),
                strict=True,
            )
        )
    )
    report = SharedSemanticImportReport(chapters, (), False)
    service = SharedSemanticOccurrenceBatchService(project, clock=lambda: _NOW)

    bound = service.persist_report(report)

    assert [item.chapter_id for item in bound.bindings] == [
        item.chapter_id for item in chapters
    ]
    assert all(item.status is OccurrenceBindingStatus.APPLIED for item in bound.bindings)
    assert bound.analysis_failures == ()
    assert bound.cancelled is False
    stored = OccurrenceRepository(project)
    total = sum(len(item.accepted_occurrence_ids) for item in bound.bindings)
    assert total == sum(len(item.results) for item in chapters)
    assert all(
        stored.get_occurrence(occurrence_id) is not None
        for item in bound.bindings
        for occurrence_id in item.accepted_occurrence_ids
    )


def test_analysis_failures_pass_through_and_never_enter_binding(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project = _project(tmp_path)
    identity = _add_chapter(project, "第一章", "艾琳行动。")
    chapter = _chapter(project, *identity, 1, "艾琳行动。")
    failure = _analysis_failure()
    calls: list[str] = []
    original = SharedSemanticOccurrenceService.persist_chapter

    def recording(self, chapter_result):
        calls.append(chapter_result.chapter_id)
        return original(self, chapter_result)

    monkeypatch.setattr(SharedSemanticOccurrenceService, "persist_chapter", recording)
    report = SharedSemanticImportReport((chapter,), (failure,), False)
    bound = SharedSemanticOccurrenceBatchService(project).persist_report(report)

    assert bound.analysis_failures == (failure,)
    assert calls == [chapter.chapter_id]
    assert len(bound.bindings) == 1


def test_middle_binding_failure_does_not_stop_later_chapters(tmp_path: Path) -> None:
    project = _project(tmp_path)
    first = _add_chapter(project, "第一章", "艾琳行动一。")
    raced = _add_chapter(project, "第二章", "艾琳行动二。")
    third = _add_chapter(project, "第三章", "艾琳行动三。")
    ChapterRepository(project).save_content(
        raced[0],
        "被并发修改的正文。",
        source="test",
        reason="source race",
        expected_revision=raced[1],
    )
    chapters = (
        _chapter(project, *first, 1, "艾琳行动一。"),
        _chapter(project, *raced, 2, "艾琳行动二。"),
        _chapter(project, *third, 3, "艾琳行动三。"),
    )
    bound = SharedSemanticOccurrenceBatchService(project).persist_report(
        SharedSemanticImportReport(chapters, (), False)
    )

    statuses = [item.status for item in bound.bindings]
    assert statuses == [
        OccurrenceBindingStatus.APPLIED,
        OccurrenceBindingStatus.FAILED,
        OccurrenceBindingStatus.APPLIED,
    ]
    assert bound.bindings[1].failure is not None
    assert (
        bound.bindings[1].failure.code
        is OccurrenceBindingFailureCode.PERSISTENCE_FAILED
    )
    assert bound.bindings[0].accepted_occurrence_ids != ()
    assert bound.bindings[2].accepted_occurrence_ids != ()
    assert bound.cancelled is False


def test_cancellation_is_only_checked_on_chapter_boundaries(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project = _project(tmp_path)
    identities = [
        _add_chapter(project, f"第{index}章", f"艾琳行动{index}。")
        for index in range(4)
    ]
    contents = tuple(f"艾琳行动{index}。" for index in range(4))
    chapters = tuple(
        _chapter(project, *identities[index], index + 1, contents[index])
        for index in range(4)
    )
    report = SharedSemanticImportReport(chapters, (), False)
    calls: list[str] = []

    def cancel_after_first() -> bool:
        return len(calls) >= 1

    original = SharedSemanticOccurrenceService.persist_chapter

    def recording(self, chapter_result):
        calls.append(chapter_result.chapter_id)
        return original(self, chapter_result)

    monkeypatch.setattr(SharedSemanticOccurrenceService, "persist_chapter", recording)
    bound = SharedSemanticOccurrenceBatchService(project).persist_report(
        report,
        should_cancel=cancel_after_first,
    )

    assert calls == [chapters[0].chapter_id]
    assert [item.chapter_id for item in bound.bindings] == calls
    assert bound.cancelled is True


def test_cancelled_before_first_chapter_binds_nothing(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project = _project(tmp_path)
    identity = _add_chapter(project, "第一章", "艾琳行动。")
    chapter = _chapter(project, *identity, 1, "艾琳行动。")
    calls: list[str] = []
    original = SharedSemanticOccurrenceService.persist_chapter

    def recording(self, chapter_result):
        calls.append(chapter_result.chapter_id)
        return original(self, chapter_result)

    monkeypatch.setattr(SharedSemanticOccurrenceService, "persist_chapter", recording)
    bound = SharedSemanticOccurrenceBatchService(project).persist_report(
        SharedSemanticImportReport((chapter,), (), False),
        should_cancel=lambda: True,
    )

    assert calls == []
    assert bound.bindings == ()
    assert bound.cancelled is True


def test_empty_report_and_zero_window_chapters_bind_without_calls(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project = _project(tmp_path)
    blank = _add_chapter(project, "空白章", " \r\n ")
    empty_chapter = _chapter(project, *blank, 1, " \r\n ")
    report = SharedSemanticImportReport((empty_chapter,), (), False)
    p1_calls: list[int] = []
    original = OccurrenceRepository.create_model_candidates_for_chapter

    def recording_create(self, chapter_id, **kwargs):
        p1_calls.append(1)
        return original(self, chapter_id, **kwargs)

    monkeypatch.setattr(
        OccurrenceRepository,
        "create_model_candidates_for_chapter",
        recording_create,
    )

    empty_bound = SharedSemanticOccurrenceBatchService(project).persist_report(report)
    nothing_bound = SharedSemanticOccurrenceBatchService(project).persist_report(
        SharedSemanticImportReport((), (), False)
    )

    assert empty_bound.bindings[0].status is OccurrenceBindingStatus.APPLIED
    assert empty_bound.bindings[0].accepted_occurrence_ids == ()
    assert nothing_bound.bindings == ()
    assert nothing_bound.cancelled is False
    assert len(p1_calls) == 1


def test_reports_never_leak_body_hash_paths_or_raw_exceptions(
    tmp_path: Path,
) -> None:
    project = _project(tmp_path)
    body = "绝密正文内容不应出现。"
    raced = _add_chapter(project, "第二章", body)
    ChapterRepository(project).save_content(
        raced[0],
        "替换后的正文。",
        source="test",
        reason="source race",
        expected_revision=raced[1],
    )
    chapter = _chapter(project, *raced, 2, body)
    bound = SharedSemanticOccurrenceBatchService(project).persist_report(
        SharedSemanticImportReport((chapter,), (_analysis_failure("第二章"),), False)
    )
    rendered = repr(bound) + str(bound)

    assert bound.bindings[0].status is OccurrenceBindingStatus.FAILED
    assert bound.bindings[0].failure is not None
    assert (
        bound.bindings[0].failure.message
        == "occurrence binding could not be persisted"
    )
    assert body not in rendered
    assert "替换后的正文" not in rendered
    assert raced[2] not in rendered
    assert "C:\\" not in rendered
    assert "sqlite" not in rendered.lower()


def test_base_exception_from_binding_propagates(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project = _project(tmp_path)
    identity = _add_chapter(project, "第一章", "艾琳行动。")
    chapter = _chapter(project, *identity, 1, "艾琳行动。")

    def stop(*args, **kwargs):
        raise KeyboardInterrupt

    monkeypatch.setattr(
        SharedSemanticOccurrenceService,
        "persist_chapter",
        stop,
    )
    with pytest.raises(KeyboardInterrupt):
        SharedSemanticOccurrenceBatchService(project).persist_report(
            SharedSemanticImportReport((chapter,), (), False)
        )


def test_no_second_manuscript_read_or_subject_creation_during_binding(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project = _project(tmp_path)
    identity = _add_chapter(project, "第一章", "艾琳行动。")
    chapter = _chapter(project, *identity, 1, "艾琳行动。")

    def forbidden_read(*args, **kwargs):
        raise AssertionError("binding must not reread manuscript content")

    monkeypatch.setattr(ChapterRepository, "read_content_exact", forbidden_read)
    with project.database.connect() as connection:
        subject_count_before = int(
            connection.execute("SELECT COUNT(*) FROM subjects").fetchone()[0]
        )

    bound = SharedSemanticOccurrenceBatchService(project).persist_report(
        SharedSemanticImportReport((chapter,), (), False)
    )

    with project.database.connect() as connection:
        subject_count_after = int(
            connection.execute("SELECT COUNT(*) FROM subjects").fetchone()[0]
        )
    assert bound.bindings[0].status is OccurrenceBindingStatus.APPLIED
    assert subject_count_after == subject_count_before


def test_input_envelopes_are_validated(tmp_path: Path) -> None:
    project = _project(tmp_path)

    with pytest.raises(TypeError, match="project"):
        SharedSemanticOccurrenceBatchService(object())  # type: ignore[arg-type]
    with pytest.raises(TypeError, match="clock"):
        SharedSemanticOccurrenceBatchService(project, clock="invalid")  # type: ignore[arg-type]
    service = SharedSemanticOccurrenceBatchService(project)
    with pytest.raises(TypeError, match="report"):
        service.persist_report(object())  # type: ignore[arg-type]
    with pytest.raises(TypeError, match="cancellation"):
        service.persist_report(
            SharedSemanticImportReport((), (), False),
            should_cancel="invalid",  # type: ignore[arg-type]
        )


def test_binding_report_dto_is_immutable_and_validated() -> None:
    failure = _analysis_failure()
    report = OccurrenceImportBindingReport((), (failure,), False)

    assert {item.name for item in fields(report)} == {
        "bindings",
        "analysis_failures",
        "cancelled",
    }
    assert report.analysis_failures == (failure,)
    assert report.cancelled is False
    with pytest.raises(ValueError):
        OccurrenceImportBindingReport(("not-a-binding",), (), False)  # type: ignore[arg-type]
    with pytest.raises(ValueError):
        OccurrenceImportBindingReport((), ("not-a-failure",), False)  # type: ignore[arg-type]
    with pytest.raises(ValueError):
        OccurrenceImportBindingReport((), (), "cancelled")  # type: ignore[arg-type]
