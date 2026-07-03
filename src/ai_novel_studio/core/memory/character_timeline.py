from __future__ import annotations

from dataclasses import dataclass

from ai_novel_studio.domain.memory import (
    Character,
    CharacterStateEvent,
    KnowledgeSubject,
)
from ai_novel_studio.infrastructure.storage.character_memory_repository import (
    CharacterMemoryRepository,
    KnowledgeSnapshotEntry,
)


@dataclass(frozen=True, slots=True)
class CharacterTimelineSnapshot:
    character: Character
    state: CharacterStateEvent | None
    conflicting_states: tuple[CharacterStateEvent, ...]
    knowledge: tuple[KnowledgeSnapshotEntry, ...]


class CharacterTimeline:
    def __init__(self, repository: CharacterMemoryRepository) -> None:
        self.repository = repository

    def snapshot(
        self,
        character_ids: tuple[str, ...],
        before_chapter_id: str,
    ) -> tuple[CharacterTimelineSnapshot, ...]:
        snapshots: list[CharacterTimelineSnapshot] = []
        for character_id in character_ids:
            states = self.repository.state_candidates_before(
                character_id, before_chapter_id
            )
            snapshots.append(
                CharacterTimelineSnapshot(
                    character=self.repository.get_character(character_id),
                    state=states[0] if len(states) == 1 else None,
                    conflicting_states=states if len(states) > 1 else (),
                    knowledge=self.repository.knowledge_before(
                        subject_type=KnowledgeSubject.CHARACTER,
                        subject_id=character_id,
                        chapter_id=before_chapter_id,
                    ),
                )
            )
        return tuple(snapshots)
