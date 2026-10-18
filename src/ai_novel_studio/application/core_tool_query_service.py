from __future__ import annotations

from dataclasses import dataclass

from ai_novel_studio.application.evidence_query_service import (
    EvidenceQueryRequest,
    EvidenceQueryService,
)
from ai_novel_studio.application.formal_manuscript_evidence_service import (
    EvidenceSet,
    FormalManuscriptEvidenceService,
)
from ai_novel_studio.application.plan_query_service import (
    PlanQueryRequest,
    PlanQueryService,
    PlanResult,
)
from ai_novel_studio.application.project_constitution_service import (
    ProjectConstitutionService,
)
from ai_novel_studio.core.context.history_retriever import HistoryRetriever
from ai_novel_studio.domain.project_constitution import ProjectConstitution
from ai_novel_studio.domain.subject import SubjectType
from ai_novel_studio.infrastructure.storage.chapter_repository import (
    ChapterRepository,
)
from ai_novel_studio.infrastructure.storage.project_constitution_repository import (
    ProjectConstitutionRepository,
)
from ai_novel_studio.infrastructure.storage.project_repository import (
    ProjectRepository,
)
from ai_novel_studio.infrastructure.storage.search_repository import SearchRepository
from ai_novel_studio.infrastructure.storage.subject_repository import SubjectRepository


@dataclass(frozen=True, slots=True)
class ManuscriptExcerpt:
    title: str
    revision: int
    content: str
    truncated: bool


@dataclass(frozen=True, slots=True)
class SubjectQueryItem:
    subject_id: str
    canonical_name: str
    subject_type: SubjectType
    active: bool


class CoreToolQueryService:
    """Read-only backend facade for resident Harness tools."""

    def __init__(self, project: ProjectRepository) -> None:
        if not isinstance(project, ProjectRepository):
            raise TypeError("core tool project is invalid")
        self._chapters = ChapterRepository(project)
        self._subjects = SubjectRepository(project)
        self._plans = PlanQueryService(project)
        search = SearchRepository(project)
        self._evidence = EvidenceQueryService(
            retriever=HistoryRetriever(search),
            evidence=FormalManuscriptEvidenceService(search),
        )
        self._constitutions = ProjectConstitutionService(
            ProjectConstitutionRepository(project)
        )

    def read_manuscript(self, chapter_id: str, *, max_chars: int) -> ManuscriptExcerpt:
        chapter = self._chapters.get_chapter(chapter_id, include_deleted=False)
        content = self._chapters.read_content_exact(chapter_id)
        excerpt = content[:max_chars]
        return ManuscriptExcerpt(
            title=chapter.title,
            revision=chapter.revision,
            content=excerpt,
            truncated=len(content) > len(excerpt),
        )

    def read_selection(self, chapter_id: str, *, start: int, end: int) -> str:
        content = self._chapters.read_content_exact(chapter_id)
        if start < 0 or end < start or end > len(content):
            raise ValueError("manuscript selection is invalid")
        return content[start:end]

    def manuscript_length(self, chapter_id: str) -> int:
        return len(self._chapters.read_content_exact(chapter_id))

    def query_subjects(
        self, query: str, *, limit: int
    ) -> tuple[SubjectQueryItem, ...]:
        matches = list(self._subjects.resolve_character_name(query))
        if not matches:
            matches = [
                subject
                for subject in self._subjects.list_active_characters()
                if query in subject.canonical_name
                or any(
                    query in alias.alias
                    for alias in self._subjects.list_aliases(subject.id)
                )
            ]
        return tuple(
            SubjectQueryItem(
                subject_id=subject.id,
                canonical_name=subject.canonical_name,
                subject_type=subject.type,
                active=subject.active,
            )
            for subject in matches[:limit]
        )

    def query_plan(self, chapter_id: str) -> PlanResult:
        return self._plans.query(PlanQueryRequest(chapter_id))

    def query_memory(
        self,
        query: str,
        *,
        before_chapter_id: str,
        limit: int,
    ) -> EvidenceSet:
        return self._evidence.query(
            EvidenceQueryRequest(
                query=query,
                target_chapter_id=before_chapter_id,
                limit=limit,
            )
        )

    def get_constitution(self) -> ProjectConstitution | None:
        return self._constitutions.get_project_constitution()


__all__ = [
    "CoreToolQueryService",
    "ManuscriptExcerpt",
    "SubjectQueryItem",
]
