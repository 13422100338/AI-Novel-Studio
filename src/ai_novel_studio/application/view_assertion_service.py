from __future__ import annotations

from ai_novel_studio.domain.memory import Authority, ReviewStatus, SourceType
from ai_novel_studio.domain.view import ViewAssertion, ViewAssertionDraft, ViewType
from ai_novel_studio.infrastructure.storage.project_repository import ProjectRepository
from ai_novel_studio.infrastructure.storage.view_assertion_repository import (
    ViewAssertionRepository,
)


class ViewAssertionService:
    """Stores explicit assertions and exposes only context-safe records."""

    def __init__(self, project: ProjectRepository) -> None:
        self.repository = ViewAssertionRepository(project)

    def create_user_assertion(
        self,
        draft: ViewAssertionDraft,
        *,
        source_id: str,
        source_revision: int,
        confirmed_by_user: bool,
    ) -> ViewAssertion:
        if not confirmed_by_user:
            raise PermissionError("视角断言必须由用户明确确认")
        return self.repository.create(
            draft,
            authority=Authority.USER_CONFIRMED,
            review_status=ReviewStatus.APPROVED,
            source_type=SourceType.HUMAN,
            source_id=source_id,
            source_revision=source_revision,
        )

    def list_for_context(
        self,
        *,
        narrative_sequence: int,
        view_type: ViewType,
        viewer_subject_id: str | None = None,
    ) -> tuple[ViewAssertion, ...]:
        return self.repository.list_visible_at(
            narrative_sequence=narrative_sequence,
            view_type=view_type,
            viewer_subject_id=viewer_subject_id,
        )
