from __future__ import annotations

from dataclasses import dataclass

from ai_novel_studio.domain.identifiers import validate_id
from ai_novel_studio.infrastructure.storage.chapter_requirement_repository import (
    ChapterRequirementRepository,
)
from ai_novel_studio.infrastructure.storage.project_guidance_repository import (
    ProjectGuidanceRepository,
)
from ai_novel_studio.infrastructure.storage.project_repository import ProjectRepository

PLAN_DOMAIN_KIND = "AUTHOR_PLAN"


@dataclass(frozen=True, slots=True)
class PlanQueryRequest:
    chapter_id: str

    def __post_init__(self) -> None:
        try:
            object.__setattr__(
                self, "chapter_id", validate_id(self.chapter_id)
            )
        except ValueError:
            raise ValueError("plan query chapter id is invalid") from None


@dataclass(frozen=True, slots=True)
class RequirementSnapshot:
    requirement_id: str
    content: str
    is_locked: bool
    revision: int
    content_hash: str


@dataclass(frozen=True, slots=True)
class PlanResult:
    chapter_id: str
    domain_kind: str
    requirement: RequirementSnapshot | None
    guidance_text: str
    guidance_revision: int


class PlanQueryService:
    """Read-only plan query aggregating existing plan sources (V1 minimal).

    PLAN is never CANON: the result is explicitly tagged AUTHOR_PLAN and the
    Context hard filter remains the enforcement boundary.
    """

    def __init__(self, project: ProjectRepository) -> None:
        self._requirements = ChapterRequirementRepository(project)
        self._guidance = ProjectGuidanceRepository(project)

    def query(self, request: PlanQueryRequest) -> PlanResult:
        if not isinstance(request, PlanQueryRequest):
            raise TypeError("plan query request is invalid")
        try:
            requirement = self._requirements.get(request.chapter_id)
        except KeyError:
            requirement = None
        snapshot = (
            RequirementSnapshot(
                requirement_id=requirement.id,
                content=requirement.content,
                is_locked=requirement.is_locked,
                revision=requirement.revision,
                content_hash=requirement.content_hash,
            )
            if requirement is not None
            else None
        )
        guidance = self._guidance.load()
        return PlanResult(
            chapter_id=request.chapter_id,
            domain_kind=PLAN_DOMAIN_KIND,
            requirement=snapshot,
            guidance_text=guidance.highest_system_prompt,
            guidance_revision=guidance.revision,
        )
