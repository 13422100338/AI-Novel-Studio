from __future__ import annotations

import hashlib
from collections.abc import Mapping

from ai_novel_studio.core.context.context_builder import ContextBlock
from ai_novel_studio.core.context.context_filter import ContextEligibility
from ai_novel_studio.domain.chapter import Chapter
from ai_novel_studio.domain.memory import ReviewStatus
from ai_novel_studio.domain.view import ViewAssertion, ViewType
from ai_novel_studio.infrastructure.storage.chapter_repository import ChapterRepository
from ai_novel_studio.infrastructure.storage.project_repository import ProjectRepository
from ai_novel_studio.infrastructure.storage.view_assertion_repository import (
    ViewAssertionRepository,
)

MAX_CONTEXT_VIEW_ASSERTIONS = 250


class ViewAssertionContextProvider:
    """Projects persisted view assertions into auditable context candidates."""

    def __init__(self, project: ProjectRepository) -> None:
        self.chapters = ChapterRepository(project)
        self.assertions = ViewAssertionRepository(project)

    def blocks(
        self,
        chapter_id: str,
        *,
        pov_character_id: str | None,
    ) -> tuple[ContextBlock, ...]:
        narrative_sequence = len(self.chapters.list_before(chapter_id)) + 1
        candidates: list[ViewAssertion] = []
        if pov_character_id is not None:
            candidates.extend(
                self.assertions.list_context_candidates(
                    view_type=ViewType.CHARACTER_VIEW,
                    viewer_subject_id=pov_character_id,
                    limit=MAX_CONTEXT_VIEW_ASSERTIONS,
                )
            )
        candidates.extend(
            self.assertions.list_context_candidates(
                view_type=ViewType.READER_VIEW,
                limit=MAX_CONTEXT_VIEW_ASSERTIONS,
            )
        )

        chapter_sources = {
            chapter.id: chapter for chapter in self.chapters.list_chapters()
        }
        chapter_hashes = {
            source_id: _hash(self.chapters.read_content(source_id))
            for source_id in {assertion.source_id for assertion in candidates}
            if source_id in chapter_sources
        }
        return tuple(
            self._block(
                assertion,
                narrative_sequence=narrative_sequence,
                priority=12 + index,
                chapter_sources=chapter_sources,
                chapter_hashes=chapter_hashes,
            )
            for index, assertion in enumerate(candidates)
        )

    def replaced_legacy_reader_event_ids(
        self,
        chapter_id: str,
        event_ids: tuple[str, ...],
    ) -> frozenset[str]:
        """Return legacy reader events explicitly replaced by safe reader views."""
        if not event_ids:
            return frozenset()
        narrative_sequence = len(self.chapters.list_before(chapter_id)) + 1
        known_event_ids = frozenset(event_ids)
        candidates = self.assertions.list_context_candidates(
            view_type=ViewType.READER_VIEW,
            limit=MAX_CONTEXT_VIEW_ASSERTIONS,
        )
        return frozenset(
            assertion.source_id
            for assertion in candidates
            if assertion.source_id in known_event_ids
            and assertion.review_status in {ReviewStatus.APPROVED, ReviewStatus.LOCKED}
            and not assertion.stale
            and not assertion.source_changed
            and self._time_visible(assertion, narrative_sequence)
        )

    def _block(
        self,
        assertion: ViewAssertion,
        *,
        narrative_sequence: int,
        priority: int,
        chapter_sources: Mapping[str, Chapter],
        chapter_hashes: Mapping[str, str],
    ) -> ContextBlock:
        content = self._content(assertion)
        source_chapter = chapter_sources.get(assertion.source_id)
        source_chapter_id: str | None = None
        source_hash = _hash(content)
        revision_current = True
        if source_chapter is not None:
            source_chapter_id = assertion.source_id
            current_revision = source_chapter.revision
            if not assertion.stale and not assertion.source_changed:
                revision_current = current_revision == assertion.source_revision
            source_hash = chapter_hashes[assertion.source_id]

        return ContextBlock(
            id=f"view-assertion-{assertion.id}",
            category="MEMORY",
            content=content,
            priority=priority,
            required=False,
            source_type=f"VIEW_ASSERTION/{assertion.view_type.value}",
            source_id=assertion.id,
            source_chapter_id=source_chapter_id,
            source_revision=assertion.source_revision,
            source_hash=source_hash,
            rationale=self._rationale(assertion),
            eligibility=ContextEligibility(
                revision_current=revision_current,
                time_visible=self._time_visible(assertion, narrative_sequence),
                authority_allowed=assertion.review_status
                in {ReviewStatus.APPROVED, ReviewStatus.LOCKED},
                stale=assertion.stale,
                source_changed=assertion.source_changed,
            ),
        )

    @staticmethod
    def _content(assertion: ViewAssertion) -> str:
        if assertion.view_type == ViewType.READER_VIEW:
            return f"读者知识边界：{assertion.content}"
        status = assertion.epistemic_status.value if assertion.epistemic_status else "UNKNOWN"
        return f"POV 知识/{status}：{assertion.content}"

    @staticmethod
    def _rationale(assertion: ViewAssertion) -> str:
        if assertion.view_type == ViewType.READER_VIEW:
            return "当前章节读者可见性候选"
        return "冻结 Brief 指定 POV 的人物知识候选"

    @staticmethod
    def _time_visible(assertion: ViewAssertion, sequence: int) -> bool:
        return _in_range(
            sequence,
            assertion.valid_from_sequence,
            assertion.valid_to_sequence,
        ) and _in_range(
            sequence,
            assertion.narrative_visible_from_sequence,
            assertion.narrative_visible_to_sequence,
        )


def _in_range(value: int, start: int | None, end: int | None) -> bool:
    return (start is None or start <= value) and (end is None or value <= end)


def _hash(content: str) -> str:
    return hashlib.sha256(content.encode("utf-8")).hexdigest()
