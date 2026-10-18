"""Bounded read-only projection over the approved clue ledger (QP-3A).

Reuses :class:`NarrativeMemoryRepository.clue_timelines_before` as the single
truth source: only ``CURRENT`` clues with ``APPROVED``/``LOCKED`` reviews and
events strictly before the target chapter in canonical narrative order. The
projection truncates long details, caps result sizes deterministically, and
performs no writes.
"""

from __future__ import annotations

from dataclasses import dataclass

from ai_novel_studio.infrastructure.storage.chapter_repository import (
    ChapterRepository,
)
from ai_novel_studio.infrastructure.storage.narrative_memory_repository import (
    NarrativeMemoryRepository,
)
from ai_novel_studio.infrastructure.storage.project_repository import (
    ProjectRepository,
)

_MAX_CLUES = 200
_MAX_EVENTS_PER_CLUE = 50
_MAX_SUMMARY_CODEPOINTS = 200


@dataclass(frozen=True, slots=True)
class ClueItem:
    clue_id: str
    title: str
    clue_type: str
    status: str
    review_status: str
    event_count: int
    last_action: str
    last_chapter_id: str
    summary: str
    summary_truncated: bool
    chapter_ids: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class ClueLedgerProjection:
    chapter_id: str
    items: tuple[ClueItem, ...]


def _truncate(text: str, limit: int) -> tuple[str, bool]:
    if len(text) <= limit:
        return text, False
    return text[:limit], True


class NarrativeClueReadService:
    def __init__(self, project: ProjectRepository) -> None:
        self._project = project
        self._memory = NarrativeMemoryRepository(project)

    def list_clues_before(self, chapter_id: str) -> tuple[ClueItem, ...]:
        return self.projection_for(chapter_id).items

    def projection_for(self, chapter_id: str) -> ClueLedgerProjection:
        chapters = ChapterRepository(self._project)
        try:
            chapters.get_chapter(chapter_id, include_deleted=False)
        except KeyError as error:
            raise ValueError(str(error)) from None
        # SQL-level bounds (RC-4): the repository query itself is capped so
        # large projects never load unbounded rows into memory. The ROW_NUMBER
        # ranks the ALREADY-ELIGIBLE set (approved + strictly before target),
        # so later-chapter events can never crowd out earlier evidence.
        timelines, totals = self._memory.bounded_clue_timelines_before(
            chapter_id,
            max_clues=_MAX_CLUES,
            max_events_per_clue=_MAX_EVENTS_PER_CLUE,
        )
        items: list[ClueItem] = []
        for timeline in timelines:
            # Clue rows are project-global; only their events carry chapter
            # scope. A clue with no before-target approved event is not yet
            # part of the story so far and stays invisible here.
            if not timeline.events:
                continue
            last = timeline.events[-1]
            detail = (timeline.clue.detail or "").strip()
            summary, truncated = _truncate(
                detail if detail else (last.detail if last else ""),
                _MAX_SUMMARY_CODEPOINTS,
            )
            items.append(
                ClueItem(
                    clue_id=timeline.clue.id,
                    title=timeline.clue.title,
                    clue_type=timeline.clue.clue_type.value,
                    status=timeline.clue.status.value,
                    review_status=timeline.clue.review_status.value,
                    event_count=totals.get(timeline.clue.id, len(timeline.events)),
                    last_action=(last.action.value if last else ""),
                    last_chapter_id=(last.chapter_id if last else ""),
                    summary=summary,
                    summary_truncated=truncated,
                    chapter_ids=tuple(event.chapter_id for event in timeline.events),
                )
            )
        return ClueLedgerProjection(chapter_id=chapter_id, items=tuple(items))
