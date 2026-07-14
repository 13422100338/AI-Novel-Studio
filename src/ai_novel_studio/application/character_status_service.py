from __future__ import annotations

from dataclasses import dataclass

from ai_novel_studio.domain.memory import ReviewStatus, SourceType
from ai_novel_studio.infrastructure.storage.character_memory_repository import (
    CharacterMemoryRepository,
    MemoryConflictError,
)


@dataclass(frozen=True, slots=True)
class CharacterStatusRecord:
    id: str
    name: str
    profile: str
    motivation: str
    psychology: str
    goal: str
    relationships: str
    recent: str


class CharacterStatusService:
    def __init__(self, repository: CharacterMemoryRepository) -> None:
        self.repository = repository

    def list_for_chapter(self, chapter_id: str) -> tuple[CharacterStatusRecord, ...]:
        characters = self.repository.list_characters()
        states_by_character = self.repository.state_candidates_before_many(
            tuple(character.id for character in characters),
            chapter_id,
            inclusive=True,
        )
        records: list[CharacterStatusRecord] = []
        for character in characters:
            candidates = states_by_character.get(character.id, ())
            if len(candidates) > 1:
                raise MemoryConflictError("同一时间边界存在多个人物状态")
            state = candidates[0] if candidates else None
            records.append(
                CharacterStatusRecord(
                    id=character.id,
                    name=character.canonical_name,
                    profile=character.profile,
                    motivation=state.motivation if state is not None else "",
                    psychology=state.psychology if state is not None else "",
                    goal=state.current_goal if state is not None else "",
                    relationships=state.relationships if state is not None else "",
                    recent=state.recent_activity if state is not None else "",
                )
            )
        return tuple(records)

    def save(
        self,
        chapter_id: str,
        *,
        character_id: str | None,
        name: str,
        motivation: str,
        psychology: str,
        goal: str,
        relationships: str = "",
        recent: str,
    ) -> CharacterStatusRecord:
        normalized_name = name.strip()
        if not normalized_name:
            raise ValueError("人物名称不能为空")

        character = None
        if character_id:
            try:
                character = self.repository.get_character(character_id)
            except KeyError:
                character = None
        if character is None:
            character = self.repository.create_character(normalized_name)

        event = self.repository.append_state(
            character.id,
            chapter_id,
            motivation=motivation,
            psychology=psychology,
            current_goal=goal,
            relationships=relationships,
            recent_activity=recent,
            confidence=1.0,
            source_type=SourceType.HUMAN,
            review_status=ReviewStatus.APPROVED,
        )
        return CharacterStatusRecord(
            id=character.id,
            name=character.canonical_name,
            profile=character.profile,
            motivation=event.motivation,
            psychology=event.psychology,
            goal=event.current_goal,
            relationships=event.relationships,
            recent=event.recent_activity,
        )
