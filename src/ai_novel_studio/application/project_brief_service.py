from __future__ import annotations

from ai_novel_studio.application.brief_context_provider import (
    BriefCompilationRequest,
    BriefContextProvider,
)
from ai_novel_studio.application.brief_lifecycle_service import (
    BriefCloneResult,
    BriefLifecycleService,
    BriefValidationError,
)
from ai_novel_studio.application.chapter_brief_compiler import ChapterBriefCompiler
from ai_novel_studio.core.context.history_retriever import HistoryRetriever
from ai_novel_studio.domain.generation import BriefStatus, ChapterBrief, CreationMode
from ai_novel_studio.infrastructure.storage.chapter_brief_repository import (
    BriefDraftData,
    ChapterBriefRepository,
)
from ai_novel_studio.infrastructure.storage.chapter_requirement_repository import (
    ChapterRequirementRepository,
)
from ai_novel_studio.infrastructure.storage.character_memory_repository import (
    CharacterMemoryRepository,
)
from ai_novel_studio.infrastructure.storage.narrative_memory_repository import (
    NarrativeMemoryRepository,
)
from ai_novel_studio.infrastructure.storage.project_repository import ProjectRepository
from ai_novel_studio.infrastructure.storage.search_repository import SearchRepository
from ai_novel_studio.infrastructure.storage.style_repository import StyleRepository


class ProjectBriefService:
    """Coordinates real project Brief persistence without leaking storage into UI."""

    def __init__(
        self,
        project: ProjectRepository,
        history: HistoryRetriever,
    ) -> None:
        self.repository = ChapterBriefRepository(project)
        self.requirements = ChapterRequirementRepository(project)
        provider = BriefContextProvider(
            project,
            self.requirements,
            CharacterMemoryRepository(project),
            NarrativeMemoryRepository(project),
            StyleRepository(project),
            SearchRepository(project),
            self.repository,
            history,
        )
        self.compiler = ChapterBriefCompiler(provider, self.repository)
        self.lifecycle = BriefLifecycleService(self.repository, provider)

    def load_or_compile(self, chapter_id: str, target_length: int) -> ChapterBrief:
        existing = self.repository.list_for_chapter(chapter_id)
        for status in (BriefStatus.DRAFT, BriefStatus.FROZEN, BriefStatus.STALE):
            candidates = tuple(item for item in existing if item.status == status)
            if candidates:
                return candidates[-1]
        requirement = self.requirements.get(chapter_id)
        return self.compiler.compile(
            BriefCompilationRequest(
                chapter_id=chapter_id,
                mode=CreationMode.STANDARD,
                expected_requirement_revision=requirement.revision,
                target_length=max(1, target_length),
                story_date="",
                pov_character_id=None,
                participants=(),
            )
        ).brief

    def save(self, brief_id: str, data: BriefDraftData, revision: int) -> ChapterBrief:
        if not data.dramatic_purpose.strip() and not data.hard_events:
            raise BriefValidationError("Brief 必须包含戏剧功能或必须事件")
        return self.repository.update_draft(
            brief_id, data, expected_revision=revision
        )

    def freeze(self, brief_id: str, revision: int) -> ChapterBrief:
        return self.lifecycle.freeze(brief_id, expected_revision=revision)

    def clone(self, brief_id: str) -> BriefCloneResult:
        return self.lifecycle.clone_as_draft(brief_id)

    def recompile(self, chapter_id: str, target_length: int) -> ChapterBrief:
        requirement = self.requirements.get(chapter_id)
        return self.compiler.compile(
            BriefCompilationRequest(
                chapter_id=chapter_id,
                mode=CreationMode.STANDARD,
                expected_requirement_revision=requirement.revision,
                target_length=max(1, target_length),
                story_date="",
                pov_character_id=None,
                participants=(),
            )
        ).brief
