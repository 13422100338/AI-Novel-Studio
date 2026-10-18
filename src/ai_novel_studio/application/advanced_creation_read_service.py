"""Application facade owning all advanced-creation reads (RC-4).

The QML bridge/facade delegates here and never touches storage or retrieval
composition itself. This class reuses the canonical services:

- clue ledger: ``NarrativeMemoryRepository`` bounded queries
- chapter plan: ``PlanQueryService`` / ``ChapterPlanReadService``
- character cognition: ``ViewAssertionService.list_for_context`` (SQL limit)
- trajectory + evidence: ``SubjectHistoryService`` composed with the
  existing ``EvidenceQueryService`` boundary

Everything is read-only, deterministically ordered, and query-level bounded.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from ai_novel_studio.application.chapter_plan_read_service import (
    ChapterPlanReadService,
)
from ai_novel_studio.application.character_view_read_service import (
    CognitionRow,
)
from ai_novel_studio.application.evidence_query_service import (
    EvidenceQueryService,
)
from ai_novel_studio.application.formal_manuscript_evidence_service import (
    FormalEvidenceLimits,
    FormalManuscriptEvidenceService,
)
from ai_novel_studio.application.narrative_clue_read_service import ClueItem
from ai_novel_studio.core.context.history_retriever import HistoryRetriever
from ai_novel_studio.infrastructure.storage.chapter_repository import (
    ChapterRepository,
)
from ai_novel_studio.infrastructure.storage.project_repository import (
    ProjectRepository,
)
from ai_novel_studio.infrastructure.storage.search_repository import (
    SearchRepository,
)

_MAX_CLUES = 200
_MAX_EVENTS_PER_CLUE = 50
_MAX_COGNITION_ROWS = 200


@dataclass(frozen=True, slots=True)
class BoundedClueLedger:
    chapter_id: str
    items: tuple[ClueItem, ...]


class AdvancedCreationReadService:
    """Single application entry point for the advanced creation page."""

    def __init__(self, project: ProjectRepository) -> None:
        self._project = project
        self._chapters = ChapterRepository(project)
        self._plans = ChapterPlanReadService(project)
        repository = SearchRepository(project)
        self._history = self._build_history_service(project, repository)

    @staticmethod
    def _build_history_service(
        project: ProjectRepository,
        repository: SearchRepository,
    ) -> Any:
        from ai_novel_studio.application.subject_history_service import (
            SubjectHistoryService,
        )

        return SubjectHistoryService(
            project,
            evidence_query=EvidenceQueryService(
                retriever=HistoryRetriever(repository),
                evidence=FormalManuscriptEvidenceService(
                    repository,
                    limits=FormalEvidenceLimits(),
                ),
            ),
        )

    # -- shared ------------------------------------------------------------

    def current_sequence(self, chapter_id: str) -> int:
        try:
            return self._chapters.get_chapter_sequence(chapter_id)
        except KeyError:
            return 0

    # -- clue ledger ---------------------------------------------------------

    def clues_before(self, chapter_id: str) -> tuple[ClueItem, ...]:
        """Delegate to the canonical bounded clue projection (RC-4 dedup)."""
        from ai_novel_studio.application.narrative_clue_read_service import (
            NarrativeClueReadService,
        )

        return NarrativeClueReadService(self._project).list_clues_before(
            chapter_id
        )

    # -- chapter plan --------------------------------------------------------

    def plan(self, chapter_id: str) -> Any:
        return self._plans.plan_for(chapter_id)

    # -- cognition -----------------------------------------------------------

    def cognition_rows(
        self,
        viewer_subject_id: str | None,
        narrative_sequence: int,
    ) -> tuple[CognitionRow, ...]:
        from ai_novel_studio.application.character_view_read_service import (
            CharacterViewReadService,
        )

        service = CharacterViewReadService(self._project)
        return service.views_for(
            viewer_subject_id=viewer_subject_id,
            narrative_sequence=narrative_sequence,
            limit=_MAX_COGNITION_ROWS,
        )

    # -- trajectory ----------------------------------------------------------

    def trajectory_index(self, subject_id: str) -> tuple[Any, ...]:
        items: tuple[Any, ...] = self._history.list_index(subject_id)
        return items

    def trajectory_detail(self, occurrence_id: str) -> Any:
        return self._history.get_detail(occurrence_id.strip())

    def trajectory_evidence(self, occurrence_id: str, target_chapter_id: str) -> Any:
        return self._history.get_evidence(
            occurrence_id.strip(),
            target_chapter_id=target_chapter_id,
        )
