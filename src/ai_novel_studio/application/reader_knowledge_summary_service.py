from __future__ import annotations

import hashlib
from dataclasses import dataclass

from ai_novel_studio.domain.memory import (
    Authority,
    KnowledgeState,
    KnowledgeSubject,
    ReviewStatus,
)
from ai_novel_studio.infrastructure.storage.chapter_repository import ChapterRepository
from ai_novel_studio.infrastructure.storage.character_memory_repository import (
    CharacterMemoryRepository,
    KnowledgeSnapshotEntry,
)
from ai_novel_studio.infrastructure.storage.project_repository import ProjectRepository

READER_SUMMARY_OVERRIDE_TITLE = "读者当前知识摘要（人工覆盖）"
READER_SUMMARY_RECORD_ID = "reader-knowledge-summary"


@dataclass(frozen=True, slots=True)
class ReaderKnowledgeSummary:
    content: str
    content_hash: str
    source_event_ids: tuple[str, ...]
    entries: tuple[KnowledgeSnapshotEntry, ...]
    source_chapter_id: str
    authority: Authority
    review_status: ReviewStatus


class ReaderKnowledgeSummaryService:
    """Aggregate reader-knowledge events into one plain-language, time-bounded card."""

    def __init__(self, project: ProjectRepository) -> None:
        self.project = project
        self.chapters = ChapterRepository(project)
        self.knowledge = CharacterMemoryRepository(project)

    def summary_before(self, chapter_id: str) -> ReaderKnowledgeSummary | None:
        entries = self.knowledge.knowledge_before(
            KnowledgeSubject.READER,
            self.project.project.id,
            chapter_id,
        )
        return self._summarize(entries)

    def summary_all(self) -> ReaderKnowledgeSummary | None:
        entries = self.knowledge.latest_knowledge_entries(
            KnowledgeSubject.READER,
            self.project.project.id,
            include_review=True,
        )
        return self._summarize(entries)

    def _summarize(
        self, entries: tuple[KnowledgeSnapshotEntry, ...]
    ) -> ReaderKnowledgeSummary | None:
        active = tuple(
            entry
            for entry in self._ordered(entries)
            if entry.event.state
            not in {KnowledgeState.UNKNOWN, KnowledgeState.FORGOTTEN}
        )
        if not active:
            return None

        override_index = next(
            (
                index
                for index in range(len(active) - 1, -1, -1)
                if active[index].item.title == READER_SUMMARY_OVERRIDE_TITLE
            ),
            None,
        )
        selected = active[override_index:] if override_index is not None else active
        if override_index is not None:
            lines = [selected[0].item.detail]
            lines.extend(self._render_entry(entry) for entry in selected[1:])
        else:
            lines = ["【读者当前知识摘要】"]
            lines.extend(self._render_entry(entry) for entry in selected)
        content = "\n".join(line for line in lines if line.strip())
        review_status = (
            ReviewStatus.REVIEW
            if any(
                ReviewStatus.REVIEW in {entry.item.review_status, entry.event.review_status}
                for entry in selected
            )
            else ReviewStatus.APPROVED
        )
        authority = max(selected, key=lambda entry: entry.item.authority.rank).item.authority
        return ReaderKnowledgeSummary(
            content=content,
            content_hash=hashlib.sha256(content.encode("utf-8")).hexdigest(),
            source_event_ids=tuple(entry.event.id for entry in selected),
            entries=selected,
            source_chapter_id=selected[-1].event.chapter_id,
            authority=authority,
            review_status=review_status,
        )

    def _ordered(
        self, entries: tuple[KnowledgeSnapshotEntry, ...]
    ) -> tuple[KnowledgeSnapshotEntry, ...]:
        positions = {
            chapter.id: index for index, chapter in enumerate(self.chapters.list_chapters())
        }
        return tuple(
            sorted(
                entries,
                key=lambda entry: (
                    positions.get(entry.event.chapter_id, 10**9),
                    entry.event.created_at,
                    entry.event.id,
                ),
            )
        )

    @staticmethod
    def _render_entry(entry: KnowledgeSnapshotEntry) -> str:
        prefix = {
            KnowledgeState.KNOWN: "读者已经知道",
            KnowledgeState.SUSPECTED: "读者目前怀疑",
            KnowledgeState.MISUNDERSTOOD: "读者目前误以为",
        }[entry.event.state]
        return f"{prefix}：{entry.item.title}。{entry.item.detail}"
