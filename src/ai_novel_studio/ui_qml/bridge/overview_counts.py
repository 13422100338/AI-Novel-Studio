"""Read-only overview counts for the QML page skeletons.

Frontend Wave F9: characters / memory / audit pages show live counts read
through existing application services (and their framework-neutral gateway),
without writing anything and without touching repositories from QML. Every
query is independent and fails safe: a broken subsystem shows ``None`` (UI
renders ``—``) instead of blocking project loading.
"""

from __future__ import annotations

from dataclasses import dataclass

from ai_novel_studio.application.character_status_service import CharacterStatusService
from ai_novel_studio.application.memory_workspace_service import MemoryWorkspaceService
from ai_novel_studio.application.project_audit_service import ProjectAuditService
from ai_novel_studio.application.project_memory_workspace_gateway import (
    ProjectMemoryWorkspaceGateway,
)
from ai_novel_studio.infrastructure.storage.character_memory_repository import (
    CharacterMemoryRepository,
)
from ai_novel_studio.infrastructure.storage.project_repository import ProjectRepository


@dataclass(frozen=True, slots=True)
class OverviewCounts:
    character_count: int | None = None
    memory_count: int | None = None
    audit_count: int | None = None


def readonly_overview_counts(
    project: ProjectRepository,
    chapter_id: str,
) -> OverviewCounts:
    """Return per-page counts; each failing query degrades to ``None``."""
    characters: int | None = None
    memory: int | None = None
    audit: int | None = None

    try:
        cards = CharacterStatusService(
            CharacterMemoryRepository(project)
        ).list_cards_for_chapter(chapter_id, inclusive=True)
        characters = len(cards)
    except (KeyError, LookupError, OSError, RuntimeError, ValueError):
        characters = None

    try:
        gateway = ProjectMemoryWorkspaceGateway(project)
        snapshot = MemoryWorkspaceService(gateway).load(chapter_id)
        memory = len(snapshot.records)
    except (KeyError, LookupError, OSError, RuntimeError, ValueError):
        memory = None

    try:
        findings = ProjectAuditService(project).latest_model_findings(chapter_id)
        audit = len(findings)
    except (KeyError, LookupError, OSError, RuntimeError, ValueError):
        audit = None

    return OverviewCounts(
        character_count=characters,
        memory_count=memory,
        audit_count=audit,
    )

