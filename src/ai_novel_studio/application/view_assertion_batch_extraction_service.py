from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol

from ai_novel_studio.application.view_assertion_service import (
    ViewAssertionExtractionAlreadyExistsError,
)
from ai_novel_studio.domain.chapter import Chapter
from ai_novel_studio.domain.view import ViewAssertion
from ai_novel_studio.infrastructure.storage.chapter_repository import ChapterRepository
from ai_novel_studio.infrastructure.storage.project_repository import ProjectRepository

_MAX_CHAPTERS = 10
_SKIPPED_MESSAGE = "当前修订已有有效的模型 View Assertion 候选，已跳过。"
_FAILED_MESSAGE = (
    "View Assertion 候选提取失败。请检查章节、人物和模型配置后重试。"
)


class ViewAssertionChapterExtractor(Protocol):
    def extract_current_chapter(
        self, chapter_id: str
    ) -> tuple[ViewAssertion, ...]: ...


class ViewAssertionBatchChapterStatus(StrEnum):
    CREATED = "CREATED"
    SKIPPED = "SKIPPED"
    FAILED = "FAILED"


@dataclass(frozen=True, slots=True)
class ViewAssertionBatchProgress:
    current: int
    total: int
    chapter_id: str
    chapter_title: str


@dataclass(frozen=True, slots=True)
class ViewAssertionBatchChapterResult:
    chapter_id: str
    chapter_title: str
    status: ViewAssertionBatchChapterStatus
    created_count: int
    message: str


@dataclass(frozen=True, slots=True)
class ViewAssertionBatchExtractionReport:
    chapters: tuple[ViewAssertionBatchChapterResult, ...]
    cancelled: bool


class ViewAssertionBatchExtractionService:
    """Sequentially extracts an explicit bounded set of chapters."""

    def __init__(
        self,
        project: ProjectRepository,
        extractor: ViewAssertionChapterExtractor,
    ) -> None:
        self._project = project
        self._extractor = extractor

    def extract_chapters(
        self,
        chapter_ids: tuple[str, ...],
        *,
        progress: Callable[[ViewAssertionBatchProgress], None] | None = None,
        should_cancel: Callable[[], bool] | None = None,
    ) -> ViewAssertionBatchExtractionReport:
        ordered_chapters = self._ordered_chapters(chapter_ids)
        results: list[ViewAssertionBatchChapterResult] = []
        cancelled = False
        total = len(ordered_chapters)

        for current, chapter in enumerate(ordered_chapters, start=1):
            if should_cancel is not None and should_cancel():
                cancelled = True
                break
            if progress is not None:
                progress(
                    ViewAssertionBatchProgress(
                        current=current,
                        total=total,
                        chapter_id=chapter.id,
                        chapter_title=chapter.title,
                    )
                )
            try:
                assertions = self._extractor.extract_current_chapter(chapter.id)
            except ViewAssertionExtractionAlreadyExistsError:
                result = ViewAssertionBatchChapterResult(
                    chapter_id=chapter.id,
                    chapter_title=chapter.title,
                    status=ViewAssertionBatchChapterStatus.SKIPPED,
                    created_count=0,
                    message=_SKIPPED_MESSAGE,
                )
            except Exception:
                result = ViewAssertionBatchChapterResult(
                    chapter_id=chapter.id,
                    chapter_title=chapter.title,
                    status=ViewAssertionBatchChapterStatus.FAILED,
                    created_count=0,
                    message=_FAILED_MESSAGE,
                )
            else:
                created_count = len(assertions)
                result = ViewAssertionBatchChapterResult(
                    chapter_id=chapter.id,
                    chapter_title=chapter.title,
                    status=ViewAssertionBatchChapterStatus.CREATED,
                    created_count=created_count,
                    message=f"已创建 {created_count} 条待审查 View Assertion 候选。",
                )
            results.append(result)
            if should_cancel is not None and should_cancel():
                cancelled = True
                break

        return ViewAssertionBatchExtractionReport(
            chapters=tuple(results),
            cancelled=cancelled,
        )

    def _ordered_chapters(self, chapter_ids: tuple[str, ...]) -> tuple[Chapter, ...]:
        if not chapter_ids:
            raise ValueError("chapter_ids must contain at least one chapter")
        if len(chapter_ids) > _MAX_CHAPTERS:
            raise ValueError(f"chapter_ids may contain at most {_MAX_CHAPTERS} chapters")
        if len(set(chapter_ids)) != len(chapter_ids):
            raise ValueError("chapter_ids must contain distinct chapter IDs")

        selected_ids = frozenset(chapter_ids)
        repository = ChapterRepository(self._project)
        ordered_chapters = tuple(
            chapter
            for volume in self._project.list_volumes()
            for chapter in repository.list_chapters(volume.id)
            if chapter.id in selected_ids
        )
        if len(ordered_chapters) != len(selected_ids):
            raise ValueError("chapter_ids contains an unknown or deleted chapter")
        return ordered_chapters
