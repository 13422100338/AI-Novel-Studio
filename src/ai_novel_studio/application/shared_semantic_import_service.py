from __future__ import annotations

import hashlib
from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol

from ai_novel_studio.core.context.semantic_windowing import (
    DEFAULT_SEMANTIC_WINDOW_POLICY,
    SemanticWindow,
    SemanticWindowPolicy,
    project_semantic_windows,
)
from ai_novel_studio.core.context.shared_semantic_result import SharedSemanticResult
from ai_novel_studio.infrastructure.storage.chapter_repository import ChapterRepository
from ai_novel_studio.infrastructure.storage.project_repository import ProjectRepository


class SharedSemanticAnalyzer(Protocol):
    def extract(self, window: SemanticWindow) -> SharedSemanticResult: ...


class SharedSemanticImportFailureCode(StrEnum):
    ANALYSIS_FAILED = "ANALYSIS_FAILED"
    SOURCE_CHANGED = "SOURCE_CHANGED"


@dataclass(frozen=True, slots=True)
class SharedSemanticChapterResult:
    chapter_id: str
    source_revision: int
    source_hash: str
    narrative_sequence: int
    results: tuple[SharedSemanticResult, ...]

    def __post_init__(self) -> None:
        if (
            not isinstance(self.chapter_id, str)
            or not self.chapter_id
            or isinstance(self.source_revision, bool)
            or not isinstance(self.source_revision, int)
            or self.source_revision < 0
            or not isinstance(self.source_hash, str)
            or len(self.source_hash) != 64
            or any(character not in "0123456789abcdef" for character in self.source_hash)
            or isinstance(self.narrative_sequence, bool)
            or not isinstance(self.narrative_sequence, int)
            or self.narrative_sequence < 1
            or not isinstance(self.results, tuple)
        ):
            raise ValueError("shared semantic chapter result is invalid")
        if any(
            not isinstance(result, SharedSemanticResult)
            or result.window.chapter_id != self.chapter_id
            or result.window.source_revision != self.source_revision
            or result.window.source_hash != self.source_hash
            or result.window.narrative_sequence != self.narrative_sequence
            or result.window.window_ordinal != ordinal
            for ordinal, result in enumerate(self.results)
        ):
            raise ValueError("shared semantic chapter result is invalid")


@dataclass(frozen=True, slots=True)
class SharedSemanticImportFailure:
    chapter_id: str
    chapter_title: str
    code: SharedSemanticImportFailureCode
    message: str

    def __post_init__(self) -> None:
        if (
            not isinstance(self.chapter_id, str)
            or not self.chapter_id
            or not isinstance(self.chapter_title, str)
            or not self.chapter_title.strip()
            or not isinstance(self.code, SharedSemanticImportFailureCode)
            or self.message
            not in {
                "shared semantic analysis failed",
                "chapter source changed during analysis",
            }
        ):
            raise ValueError("shared semantic import failure is invalid")


@dataclass(frozen=True, slots=True)
class SharedSemanticImportReport:
    chapters: tuple[SharedSemanticChapterResult, ...]
    failures: tuple[SharedSemanticImportFailure, ...]
    cancelled: bool

    def __post_init__(self) -> None:
        if (
            not isinstance(self.chapters, tuple)
            or not isinstance(self.failures, tuple)
            or not isinstance(self.cancelled, bool)
            or any(
                not isinstance(item, SharedSemanticChapterResult)
                for item in self.chapters
            )
            or any(
                not isinstance(item, SharedSemanticImportFailure)
                for item in self.failures
            )
        ):
            raise ValueError("shared semantic import report is invalid")

    @property
    def processed_chapters(self) -> int:
        return len(self.chapters)

    @property
    def processed_windows(self) -> int:
        return sum(len(chapter.results) for chapter in self.chapters)


class SharedSemanticImportService:
    def __init__(
        self,
        analyzer: SharedSemanticAnalyzer,
        *,
        window_policy: SemanticWindowPolicy = DEFAULT_SEMANTIC_WINDOW_POLICY,
    ) -> None:
        if not callable(getattr(analyzer, "extract", None)):
            raise TypeError("shared semantic analyzer is invalid")
        if not isinstance(window_policy, SemanticWindowPolicy):
            raise TypeError("shared semantic window policy is invalid")
        self._analyzer = analyzer
        self._window_policy = window_policy

    def analyze_all(
        self,
        project: ProjectRepository,
        *,
        should_cancel: Callable[[], bool] | None = None,
    ) -> SharedSemanticImportReport:
        if not isinstance(project, ProjectRepository):
            raise TypeError("shared semantic project is invalid")
        if should_cancel is not None and not callable(should_cancel):
            raise TypeError("shared semantic cancellation callback is invalid")

        chapters = ChapterRepository(project)
        chapter_results: list[SharedSemanticChapterResult] = []
        failures: list[SharedSemanticImportFailure] = []
        cancelled = False

        for narrative_sequence, chapter in enumerate(
            chapters.list_chapters(),
            start=1,
        ):
            if should_cancel is not None and should_cancel():
                cancelled = True
                break
            content = chapters.read_content_exact(chapter.id)
            source_hash = _source_hash(content)
            windows = project_semantic_windows(
                chapter.id,
                chapter.revision,
                source_hash,
                narrative_sequence,
                content,
                policy=self._window_policy,
            )
            pending: list[SharedSemanticResult] = []
            try:
                for window in windows:
                    if should_cancel is not None and should_cancel():
                        cancelled = True
                        break
                    result = self._analyzer.extract(window)
                    if not isinstance(result, SharedSemanticResult):
                        raise ValueError
                    if result.window != window:
                        raise ValueError
                    pending.append(result)
            except Exception:
                failures.append(_analysis_failed(chapter.id, chapter.title))
                continue
            if cancelled:
                break
            if not _source_is_current(
                chapters,
                chapter.id,
                chapter.revision,
                source_hash,
                content,
            ):
                failures.append(_source_changed(chapter.id, chapter.title))
                continue
            chapter_results.append(
                SharedSemanticChapterResult(
                    chapter_id=chapter.id,
                    source_revision=chapter.revision,
                    source_hash=source_hash,
                    narrative_sequence=narrative_sequence,
                    results=tuple(pending),
                )
            )

        return SharedSemanticImportReport(
            chapters=tuple(chapter_results),
            failures=tuple(failures),
            cancelled=cancelled,
        )


def _source_hash(content: str) -> str:
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


def _source_is_current(
    repository: ChapterRepository,
    chapter_id: str,
    source_revision: int,
    source_hash: str,
    content: str,
) -> bool:
    try:
        current = repository.get_chapter(chapter_id, include_deleted=False)
        current_content = repository.read_content_exact(chapter_id)
    except (KeyError, RuntimeError):
        return False
    return (
        current.revision == source_revision
        and current_content == content
        and _source_hash(current_content) == source_hash
    )


def _analysis_failed(
    chapter_id: str,
    chapter_title: str,
) -> SharedSemanticImportFailure:
    return SharedSemanticImportFailure(
        chapter_id=chapter_id,
        chapter_title=chapter_title,
        code=SharedSemanticImportFailureCode.ANALYSIS_FAILED,
        message="shared semantic analysis failed",
    )


def _source_changed(
    chapter_id: str,
    chapter_title: str,
) -> SharedSemanticImportFailure:
    return SharedSemanticImportFailure(
        chapter_id=chapter_id,
        chapter_title=chapter_title,
        code=SharedSemanticImportFailureCode.SOURCE_CHANGED,
        message="chapter source changed during analysis",
    )
