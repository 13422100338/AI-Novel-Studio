from __future__ import annotations

import hashlib
from dataclasses import dataclass

from ai_novel_studio.application.character_status_service import (
    CharacterStatusCard,
    CharacterStatusService,
)
from ai_novel_studio.infrastructure.storage.character_memory_repository import (
    CharacterMemoryRepository,
)
from ai_novel_studio.infrastructure.storage.project_repository import ProjectRepository


@dataclass(frozen=True, slots=True)
class CharacterCardContextItem:
    character_id: str
    source_state_id: str | None
    source_chapter_id: str | None
    content: str
    content_hash: str


class CharacterCardContextService:
    """Render one stable, pre-chapter context item for each character card."""

    def __init__(self, project: ProjectRepository) -> None:
        self.cards = CharacterStatusService(CharacterMemoryRepository(project))

    def items_before(self, chapter_id: str) -> tuple[CharacterCardContextItem, ...]:
        items: list[CharacterCardContextItem] = []
        for card in self.cards.list_cards_for_chapter(chapter_id):
            current = card.journey[-1] if card.journey else None
            content = self._render(card)
            items.append(
                CharacterCardContextItem(
                    character_id=card.id,
                    source_state_id=current.state_id if current is not None else None,
                    source_chapter_id=current.chapter_id if current is not None else None,
                    content=content,
                    content_hash=hashlib.sha256(content.encode("utf-8")).hexdigest(),
                )
            )
        return tuple(items)

    @staticmethod
    def _render(card: CharacterStatusCard) -> str:
        lines = [f"【人物状态卡｜{card.name}】"]
        if card.aliases:
            lines.append(f"别名：{'、'.join(card.aliases)}")
        if card.profile:
            lines.append(f"性格、语言与动作特点：{card.profile}")
        if card.psychology or card.goal:
            lines.append(f"当前心理与目标：{card.psychology}；{card.goal}")
        if card.motivation:
            lines.append(f"当前动机：{card.motivation}")
        if card.relationships:
            lines.append(f"人物关系：{card.relationships}")
        if card.recent:
            lines.append(f"近期活动：{card.recent}")

        earlier_entries = card.journey[:-1][-8:]
        if earlier_entries:
            lines.append("过往心路历程：")
            for index, entry in enumerate(earlier_entries, start=1):
                details = "；".join(
                    value
                    for value in (
                        f"心理={entry.psychology}" if entry.psychology else "",
                        f"目标={entry.goal}" if entry.goal else "",
                        f"活动={entry.recent_activity}" if entry.recent_activity else "",
                    )
                    if value
                )
                if details:
                    lines.append(f"{index}. {details}")
        return "\n".join(lines)
