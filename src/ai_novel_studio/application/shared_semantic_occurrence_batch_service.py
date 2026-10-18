from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime

from ai_novel_studio.application.shared_semantic_import_service import (
    SharedSemanticImportFailure,
    SharedSemanticImportReport,
)
from ai_novel_studio.application.shared_semantic_occurrence_service import (
    OccurrenceChapterBindingResult,
    SharedSemanticOccurrenceService,
)
from ai_novel_studio.infrastructure.storage.project_repository import ProjectRepository


@dataclass(frozen=True, slots=True)
class OccurrenceImportBindingReport:
    bindings: tuple[OccurrenceChapterBindingResult, ...]
    analysis_failures: tuple[SharedSemanticImportFailure, ...]
    cancelled: bool

    def __post_init__(self) -> None:
        if (
            not isinstance(self.bindings, tuple)
            or any(
                not isinstance(item, OccurrenceChapterBindingResult)
                for item in self.bindings
            )
            or not isinstance(self.analysis_failures, tuple)
            or any(
                not isinstance(item, SharedSemanticImportFailure)
                for item in self.analysis_failures
            )
            or not isinstance(self.cancelled, bool)
        ):
            raise ValueError("occurrence import binding report is invalid")


class SharedSemanticOccurrenceBatchService:
    def __init__(
        self,
        project: ProjectRepository,
        *,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self._binding = SharedSemanticOccurrenceService(project, clock=clock)

    def persist_report(
        self,
        report: SharedSemanticImportReport,
        *,
        should_cancel: Callable[[], bool] | None = None,
    ) -> OccurrenceImportBindingReport:
        if not isinstance(report, SharedSemanticImportReport):
            raise TypeError("occurrence batch import report is invalid")
        if should_cancel is not None and not callable(should_cancel):
            raise TypeError("occurrence batch cancellation callback is invalid")
        bindings: list[OccurrenceChapterBindingResult] = []
        cancelled = False
        for chapter in report.chapters:
            if should_cancel is not None and should_cancel():
                cancelled = True
                break
            bindings.append(self._binding.persist_chapter(chapter))
        return OccurrenceImportBindingReport(
            tuple(bindings),
            report.failures,
            cancelled,
        )


__all__ = [
    "OccurrenceImportBindingReport",
    "SharedSemanticOccurrenceBatchService",
]
