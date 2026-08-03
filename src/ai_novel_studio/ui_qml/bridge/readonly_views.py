"""Read-only list views for the character / memory / audit pages.

Frontend Wave F12 upgrades the F9 count skeletons into real read-only lists.
Every query goes through existing application services (and the framework
neutral gateway); failures degrade per page to an empty list so one broken
subsystem never blocks the others or project loading.
"""

from __future__ import annotations

from dataclasses import dataclass

from ai_novel_studio.application.character_status_service import CharacterStatusService
from ai_novel_studio.application.memory_workspace_service import MemoryWorkspaceService
from ai_novel_studio.application.project_audit_service import ProjectAuditService
from ai_novel_studio.application.project_memory_workspace_gateway import (
    ProjectMemoryWorkspaceGateway,
)
from ai_novel_studio.domain.memory import Authority, MemoryStatus, ReviewStatus
from ai_novel_studio.infrastructure.storage.character_memory_repository import (
    CharacterMemoryRepository,
)
from ai_novel_studio.infrastructure.storage.project_repository import ProjectRepository


@dataclass(frozen=True, slots=True)
class CharacterViewDto:
    id: str
    name: str
    aliases: tuple[str, ...] = ()
    profile: str = ""
    motivation: str = ""
    psychology: str = ""
    goal: str = ""
    relationships: str = ""
    recent: str = ""
    location: str = ""
    injury_status: str = ""


@dataclass(frozen=True, slots=True)
class MemoryViewDto:
    id: str
    category: str
    title: str
    content: str = ""
    source_type: str = ""
    authority: Authority | str = ""
    review_status: ReviewStatus | str = ""
    status: MemoryStatus | str = ""
    revision: int = 0


@dataclass(frozen=True, slots=True)
class AuditViewDto:
    id: str
    category: str = ""
    severity: str = ""
    evidence: str = ""
    explanation: str = ""
    confidence: float = 0.0
    status: str = ""


@dataclass(frozen=True, slots=True)
class ReadonlyViews:
    characters: tuple[CharacterViewDto, ...] = ()
    memories: tuple[MemoryViewDto, ...] = ()
    audits: tuple[AuditViewDto, ...] = ()


def readonly_views(
    project: ProjectRepository,
    chapter_id: str,
) -> ReadonlyViews:
    """Load the three read-only lists; each failing subsystem degrades to empty."""
    characters: tuple[CharacterViewDto, ...] = ()
    memories: tuple[MemoryViewDto, ...] = ()
    audits: tuple[AuditViewDto, ...] = ()

    try:
        cards = CharacterStatusService(
            CharacterMemoryRepository(project)
        ).list_cards_for_chapter(chapter_id, inclusive=True)
        characters = tuple(
            CharacterViewDto(
                id=card.id,
                name=card.name,
                aliases=card.aliases,
                profile=card.profile,
                motivation=card.motivation,
                psychology=card.psychology,
                goal=card.goal,
                relationships=card.relationships,
                recent=card.recent,
                location=card.location,
                injury_status=card.injury_status,
            )
            for card in cards
        )
    except (KeyError, LookupError, OSError, RuntimeError, ValueError):
        characters = ()

    try:
        snapshot = MemoryWorkspaceService(
            ProjectMemoryWorkspaceGateway(project)
        ).load(chapter_id)
        memories = tuple(
            MemoryViewDto(
                id=record.id,
                category=record.category,
                title=record.title,
                content=record.content,
                source_type=record.source_type,
                authority=record.authority,
                review_status=record.review_status,
                status=record.status,
                revision=record.revision,
            )
            for record in snapshot.records
        )
    except (KeyError, LookupError, OSError, RuntimeError, ValueError):
        memories = ()

    try:
        findings = ProjectAuditService(project).latest_model_findings(chapter_id)
        audits = tuple(
            AuditViewDto(
                id=finding.id,
                category=finding.category.value,
                severity=finding.severity.value,
                evidence=finding.evidence,
                explanation=finding.explanation,
                confidence=finding.confidence,
                status=finding.status.value,
            )
            for finding in findings
        )
    except (KeyError, LookupError, OSError, RuntimeError, ValueError):
        audits = ()

    return ReadonlyViews(
        characters=characters,
        memories=memories,
        audits=audits,
    )

