from __future__ import annotations

from dataclasses import dataclass

from ai_novel_studio.application.reader_knowledge_summary_service import (
    READER_SUMMARY_OVERRIDE_TITLE,
)
from ai_novel_studio.domain.memory import (
    Authority,
    KnowledgeState,
    KnowledgeSubject,
    ReviewStatus,
    SourceType,
)
from ai_novel_studio.domain.view import ViewAssertion, ViewAssertionDraft, ViewType
from ai_novel_studio.infrastructure.storage.chapter_repository import ChapterRepository
from ai_novel_studio.infrastructure.storage.character_memory_repository import (
    CharacterMemoryRepository,
)
from ai_novel_studio.infrastructure.storage.project_repository import ProjectRepository
from ai_novel_studio.infrastructure.storage.view_assertion_repository import (
    ViewAssertionRepository,
    ViewAssertionRepositoryError,
)


class ViewAssertionReviewError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class LegacyReaderViewCandidate:
    event_id: str
    title: str
    detail: str
    state: KnowledgeState
    source_chapter_id: str
    source_chapter_title: str
    narrative_visible_from_sequence: int


class ViewAssertionService:
    """Stores explicit assertions and exposes only context-safe records."""

    def __init__(self, project: ProjectRepository) -> None:
        self.project = project
        self.chapters = ChapterRepository(project)
        self.knowledge = CharacterMemoryRepository(project)
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

    def create_user_reader_view_from_legacy_event(
        self,
        draft: ViewAssertionDraft,
        *,
        legacy_event_id: str,
        confirmed_by_user: bool,
    ) -> ViewAssertion:
        """Create one reviewed reader view with verified legacy provenance."""
        if confirmed_by_user is not True:
            raise PermissionError("旧读者知识接管必须由用户明确确认")
        if draft.view_type != ViewType.READER_VIEW:
            raise ValueError("旧读者知识只能接管为 READER_VIEW")
        try:
            entry = self.knowledge.get_knowledge_entry(legacy_event_id)
        except KeyError as error:
            raise ValueError("旧知识事件不存在") from error
        if (
            entry.event.subject_type != KnowledgeSubject.READER
            or entry.event.subject_id != self.project.project.id
        ):
            raise ValueError("旧知识事件不是当前项目的读者知识")
        trusted_statuses = {ReviewStatus.APPROVED, ReviewStatus.LOCKED}
        if (
            entry.item.review_status not in trusted_statuses
            or entry.event.review_status not in trusted_statuses
        ):
            raise ValueError("旧读者知识尚未审查，不能接管")
        if entry.item.title == READER_SUMMARY_OVERRIDE_TITLE:
            raise ValueError("人工读者大摘要不能作为单条 Reader View 接管")
        if entry.event.state not in {
            KnowledgeState.KNOWN,
            KnowledgeState.SUSPECTED,
            KnowledgeState.MISUNDERSTOOD,
        }:
            raise ValueError("该旧读者知识状态不能接管")
        try:
            return self.repository.create(
                draft,
                authority=Authority.USER_CONFIRMED,
                review_status=ReviewStatus.APPROVED,
                source_type=SourceType.HUMAN,
                source_id=entry.event.id,
                source_revision=0,
                reject_active_reader_replacement=True,
            )
        except ViewAssertionRepositoryError as error:
            raise ValueError(str(error)) from error

    def list_legacy_reader_view_candidates(
        self,
    ) -> tuple[LegacyReaderViewCandidate, ...]:
        active_states = {
            KnowledgeState.KNOWN,
            KnowledgeState.SUSPECTED,
            KnowledgeState.MISUNDERSTOOD,
        }
        replaced_ids = self.repository.list_active_reader_replacement_source_ids()
        chapters = self.chapters.list_chapters()
        chapter_sequences = {
            chapter.id: index for index, chapter in enumerate(chapters, start=1)
        }
        chapter_titles = {chapter.id: chapter.title for chapter in chapters}
        candidates: list[LegacyReaderViewCandidate] = []
        for entry in self.knowledge.latest_knowledge_entries(
            KnowledgeSubject.READER,
            self.project.project.id,
        ):
            event = entry.event
            if (
                event.state not in active_states
                or event.id in replaced_ids
                or entry.item.title == READER_SUMMARY_OVERRIDE_TITLE
                or event.chapter_id not in chapter_sequences
            ):
                continue
            candidates.append(
                LegacyReaderViewCandidate(
                    event_id=event.id,
                    title=entry.item.title,
                    detail=entry.item.detail,
                    state=event.state,
                    source_chapter_id=event.chapter_id,
                    source_chapter_title=chapter_titles[event.chapter_id],
                    narrative_visible_from_sequence=(
                        chapter_sequences[event.chapter_id] + 1
                    ),
                )
            )
        return tuple(candidates)

    def replace_legacy_reader_event(
        self,
        *,
        legacy_event_id: str,
        subject_id: str,
        content: str,
        confirmed_by_user: bool,
    ) -> ViewAssertion:
        if confirmed_by_user is not True:
            raise PermissionError("旧读者知识接管必须由用户明确确认")
        try:
            event = self.knowledge.get_knowledge_entry(legacy_event_id).event
        except KeyError as error:
            raise ValueError("旧知识事件不存在") from error
        chapter_sequences = {
            chapter.id: index
            for index, chapter in enumerate(self.chapters.list_chapters(), start=1)
        }
        try:
            visible_from = chapter_sequences[event.chapter_id] + 1
        except KeyError as error:
            raise ValueError("旧知识事件的来源章节不存在") from error
        return self.create_user_reader_view_from_legacy_event(
            ViewAssertionDraft(
                subject_id=subject_id,
                view_type=ViewType.READER_VIEW,
                content=content,
                narrative_visible_from_sequence=visible_from,
            ),
            legacy_event_id=legacy_event_id,
            confirmed_by_user=True,
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
