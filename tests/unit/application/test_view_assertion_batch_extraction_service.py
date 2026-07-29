from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from threading import Event

import pytest

from ai_novel_studio.application.view_assertion_batch_extraction_service import (
    ViewAssertionBatchChapterStatus,
    ViewAssertionBatchExtractionService,
    ViewAssertionBatchProgress,
)
from ai_novel_studio.application.view_assertion_service import (
    ViewAssertionExtractionAlreadyExistsError,
)
from ai_novel_studio.infrastructure.storage.chapter_repository import ChapterRepository
from ai_novel_studio.infrastructure.storage.project_repository import ProjectRepository


class _ExtractionService:
    def __init__(
        self,
        results: dict[str, tuple[object, ...] | BaseException] | None = None,
        *,
        on_call: Callable[[str], None] | None = None,
    ) -> None:
        self.results = results or {}
        self.on_call = on_call
        self.calls: list[str] = []

    def extract_current_chapter(self, chapter_id: str) -> tuple[object, ...]:
        self.calls.append(chapter_id)
        if self.on_call is not None:
            self.on_call(chapter_id)
        result = self.results.get(chapter_id, ())
        if isinstance(result, BaseException):
            raise result
        return result


def _project_with_chapters(
    tmp_path: Path, count: int = 3
) -> tuple[ProjectRepository, tuple[str, ...]]:
    project = ProjectRepository.create(tmp_path / "project", "Batch Extraction")
    chapters = ChapterRepository(project)
    first_volume = project.list_volumes()[0]
    chapter_ids = [
        chapters.create_chapter(
            first_volume.id,
            f"Chapter {index + 1}",
            str(index + 1),
            f"Body {index + 1}",
        ).id
        for index in range(min(count, 2))
    ]
    if count > 2:
        second_volume = project.create_volume("Second Volume")
        chapter_ids.extend(
            chapters.create_chapter(
                second_volume.id,
                f"Chapter {index + 1}",
                str(index + 1),
                f"Body {index + 1}",
            ).id
            for index in range(2, count)
        )
    return project, tuple(chapter_ids)


def test_rejects_empty_duplicate_and_over_limit_inputs(tmp_path: Path) -> None:
    project, chapter_ids = _project_with_chapters(tmp_path, count=2)
    service = ViewAssertionBatchExtractionService(
        project, _ExtractionService()
    )

    with pytest.raises(ValueError, match="at least one"):
        service.extract_chapters(())
    with pytest.raises(ValueError, match="distinct"):
        service.extract_chapters((chapter_ids[0], chapter_ids[0]))
    with pytest.raises(ValueError, match="at most 10"):
        service.extract_chapters(tuple(f"chapter-{index}" for index in range(11)))


def test_orders_explicit_chapters_canonically_and_calls_each_once(
    tmp_path: Path,
) -> None:
    project, chapter_ids = _project_with_chapters(tmp_path)
    extraction = _ExtractionService(
        {chapter_id: (object(),) for chapter_id in chapter_ids}
    )
    progress: list[ViewAssertionBatchProgress] = []

    report = ViewAssertionBatchExtractionService(
        project, extraction
    ).extract_chapters(
        (chapter_ids[2], chapter_ids[0], chapter_ids[1]),
        progress=progress.append,
    )

    assert extraction.calls == list(chapter_ids)
    assert [item.chapter_id for item in report.chapters] == list(chapter_ids)
    assert [item.status for item in report.chapters] == [
        ViewAssertionBatchChapterStatus.CREATED,
        ViewAssertionBatchChapterStatus.CREATED,
        ViewAssertionBatchChapterStatus.CREATED,
    ]
    assert [item.created_count for item in report.chapters] == [1, 1, 1]
    assert [(item.current, item.total) for item in progress] == [
        (1, 3),
        (2, 3),
        (3, 3),
    ]


def test_skips_existing_revision_continues_after_failure_and_hides_details(
    tmp_path: Path,
) -> None:
    project, chapter_ids = _project_with_chapters(tmp_path)
    extraction = _ExtractionService(
        {
            chapter_ids[0]: ViewAssertionExtractionAlreadyExistsError(
                "safe internal category"
            ),
            chapter_ids[1]: RuntimeError(
                "sk-test-secret raw-model-response chapter-body-marker"
            ),
            chapter_ids[2]: (object(), object()),
        }
    )

    report = ViewAssertionBatchExtractionService(
        project, extraction
    ).extract_chapters(chapter_ids)

    assert extraction.calls == list(chapter_ids)
    assert [item.status for item in report.chapters] == [
        ViewAssertionBatchChapterStatus.SKIPPED,
        ViewAssertionBatchChapterStatus.FAILED,
        ViewAssertionBatchChapterStatus.CREATED,
    ]
    assert report.chapters[2].created_count == 2
    report_text = " ".join(item.message for item in report.chapters)
    assert "sk-test-secret" not in report_text
    assert "raw-model-response" not in report_text
    assert "chapter-body-marker" not in report_text


def test_cancel_during_current_chapter_keeps_result_and_stops_before_next(
    tmp_path: Path,
) -> None:
    project, chapter_ids = _project_with_chapters(tmp_path)
    cancelled = Event()
    extraction = _ExtractionService(
        {chapter_ids[0]: (object(),)},
        on_call=lambda _chapter_id: cancelled.set(),
    )

    report = ViewAssertionBatchExtractionService(
        project, extraction
    ).extract_chapters(chapter_ids, should_cancel=cancelled.is_set)

    assert extraction.calls == [chapter_ids[0]]
    assert len(report.chapters) == 1
    assert report.chapters[0].status == ViewAssertionBatchChapterStatus.CREATED
    assert report.chapters[0].created_count == 1
    assert report.cancelled is True

