from __future__ import annotations

from ai_novel_studio.domain.memory import Authority, ReviewStatus, SourceType
from ai_novel_studio.domain.view import ViewAssertion, ViewAssertionDraft, ViewType
from ai_novel_studio.infrastructure.storage.project_repository import ProjectRepository
from ai_novel_studio.infrastructure.storage.view_assertion_repository import (
    ViewAssertionRepository,
    ViewAssertionRepositoryError,
)


class ViewAssertionReviewError(RuntimeError):
    pass


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
        if confirmed_by_user is not True:
            raise PermissionError("视角断言必须由用户明确确认")
        return self.repository.create(
            draft,
            authority=Authority.USER_CONFIRMED,
            review_status=ReviewStatus.APPROVED,
            source_type=SourceType.HUMAN,
            source_id=source_id,
            source_revision=source_revision,
        )

    def create_model_candidate(
        self,
        draft: ViewAssertionDraft,
        *,
        source_id: str,
        source_revision: int,
    ) -> ViewAssertion:
        return self.repository.create(
            draft,
            authority=Authority.MODEL_EXTRACTED,
            review_status=ReviewStatus.REVIEW,
            source_type=SourceType.MODEL,
            source_id=source_id,
            source_revision=source_revision,
        )

    def list_review_candidates(self, *, limit: int = 100) -> tuple[ViewAssertion, ...]:
        return self.repository.list_model_review_candidates(limit=limit)

    def approve_candidate(
        self, assertion_id: str, *, confirmed_by_user: bool
    ) -> ViewAssertion:
        return self._review_candidate(
            assertion_id,
            decision=ReviewStatus.APPROVED,
            confirmed_by_user=confirmed_by_user,
        )

    def reject_candidate(
        self, assertion_id: str, *, confirmed_by_user: bool
    ) -> ViewAssertion:
        return self._review_candidate(
            assertion_id,
            decision=ReviewStatus.REJECTED,
            confirmed_by_user=confirmed_by_user,
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

    def _review_candidate(
        self,
        assertion_id: str,
        *,
        decision: ReviewStatus,
        confirmed_by_user: bool,
    ) -> ViewAssertion:
        if confirmed_by_user is not True:
            raise PermissionError("模型候选审查必须由用户明确确认")
        try:
            return self.repository.review_model_candidate(
                assertion_id,
                decision=decision,
            )
        except ViewAssertionRepositoryError as error:
            raise ViewAssertionReviewError(str(error)) from error
