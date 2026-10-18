"""Bounded chapter-plan projection over :class:`PlanQueryService` (QP-3A).

``PlanQueryService`` is the canonical plan authority (explicitly tagged
AUTHOR_PLAN). This projection only adds honest truncation and a fixed
unknown-chapter error; it never assembles plan truth from other tables.
"""

from __future__ import annotations

from dataclasses import dataclass

from ai_novel_studio.application.plan_query_service import (
    PlanQueryRequest,
    PlanQueryService,
)
from ai_novel_studio.infrastructure.storage.chapter_repository import (
    ChapterRepository,
)
from ai_novel_studio.infrastructure.storage.project_repository import (
    ProjectRepository,
)

_MAX_REQUIREMENT_CODEPOINTS = 4_000
_MAX_GUIDANCE_CODEPOINTS = 2_000


@dataclass(frozen=True, slots=True)
class RequirementView:
    requirement_id: str
    content: str
    is_locked: bool
    revision: int
    truncated: bool


@dataclass(frozen=True, slots=True)
class ChapterPlanView:
    chapter_id: str
    domain_kind: str
    requirement: RequirementView | None
    requirement_truncated: bool
    guidance_text: str
    guidance_revision: int
    guidance_truncated: bool


def _truncate(text: str, limit: int) -> tuple[str, bool]:
    if len(text) <= limit:
        return text, False
    return text[:limit], True


class ChapterPlanReadService:
    def __init__(self, project: ProjectRepository) -> None:
        self._project = project
        self._plans = PlanQueryService(project)

    def plan_for(self, chapter_id: str) -> ChapterPlanView:
        chapters = ChapterRepository(self._project)
        try:
            chapters.get_chapter(chapter_id, include_deleted=False)
        except KeyError as error:
            raise ValueError(str(error)) from None
        result = self._plans.query(PlanQueryRequest(chapter_id))
        requirement_view: RequirementView | None = None
        requirement_truncated = False
        if result.requirement is not None:
            content, requirement_truncated = _truncate(
                result.requirement.content, _MAX_REQUIREMENT_CODEPOINTS
            )
            requirement_view = RequirementView(
                requirement_id=result.requirement.requirement_id,
                content=content,
                is_locked=result.requirement.is_locked,
                revision=result.requirement.revision,
                truncated=requirement_truncated,
            )
        guidance_text, guidance_truncated = _truncate(
            result.guidance_text, _MAX_GUIDANCE_CODEPOINTS
        )
        return ChapterPlanView(
            chapter_id=result.chapter_id,
            domain_kind=result.domain_kind,
            requirement=requirement_view,
            requirement_truncated=requirement_truncated,
            guidance_text=guidance_text,
            guidance_revision=result.guidance_revision,
            guidance_truncated=guidance_truncated,
        )
