from __future__ import annotations

from ai_novel_studio.domain.memory import ClueAction
from ai_novel_studio.infrastructure.storage.narrative_memory_repository import (
    ClueTimeline,
    NarrativeMemoryRepository,
)


class NarrativeClueLedger:
    def __init__(self, repository: NarrativeMemoryRepository) -> None:
        self.repository = repository

    def active_before(self, chapter_id: str) -> tuple[ClueTimeline, ...]:
        inactive = {ClueAction.RESOLVE, ClueAction.ABANDON}
        return tuple(
            timeline
            for timeline in self.repository.clue_timelines_before(chapter_id)
            if timeline.events and timeline.events[-1].action not in inactive
        )

