from __future__ import annotations

from dataclasses import dataclass

from ai_novel_studio.domain.memory import MemoryStatus, ReviewStatus, SummaryLevel, SummaryNode
from ai_novel_studio.infrastructure.storage.summary_repository import SummaryRepository


@dataclass(frozen=True, slots=True)
class SummarySelection:
    current: SummaryNode | None
    stale: tuple[SummaryNode, ...]


class SummaryTree:
    def __init__(self, repository: SummaryRepository) -> None:
        self.repository = repository

    def best_available(
        self,
        level: SummaryLevel,
        scope_id: str,
        before_chapter_id: str,
    ) -> SummarySelection:
        summaries = self.repository.list_scope(level, scope_id)
        valid = tuple(
            summary
            for summary in summaries
            if self.repository.is_before(summary, before_chapter_id)
        )
        current = tuple(
            summary
            for summary in valid
            if summary.status == MemoryStatus.CURRENT
            and summary.review_status in {ReviewStatus.APPROVED, ReviewStatus.LOCKED}
        )
        selected = (
            max(current, key=lambda item: (item.authority.rank, item.revision, item.id))
            if current
            else None
        )
        stale = tuple(summary for summary in valid if summary.status == MemoryStatus.STALE)
        return SummarySelection(selected, stale)

