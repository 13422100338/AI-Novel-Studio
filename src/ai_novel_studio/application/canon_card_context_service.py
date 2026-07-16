from __future__ import annotations

import hashlib
from dataclasses import dataclass

from ai_novel_studio.domain.memory import CanonCategory, CanonEntry
from ai_novel_studio.infrastructure.storage.narrative_memory_repository import (
    NarrativeMemoryRepository,
)
from ai_novel_studio.infrastructure.storage.project_repository import ProjectRepository

CanonCardCategory = CanonCategory


@dataclass(frozen=True, slots=True)
class CanonCardFact:
    id: str
    title: str
    detail: str
    source_chapter_id: str | None


@dataclass(frozen=True, slots=True)
class CanonCardConflict:
    title: str
    details: tuple[str, ...]
    category: CanonCardCategory | None = None


@dataclass(frozen=True, slots=True)
class CanonContextCard:
    category: CanonCardCategory
    title: str
    facts: tuple[CanonCardFact, ...]
    conflicts: tuple[CanonCardConflict, ...]
    content: str
    content_hash: str


class CanonCardContextService:
    """Aggregate legacy canon facts into four deterministic, read-only cards."""

    _CHARACTER_WORDS = ("人物", "身份", "身世", "血统", "种族", "角色", "姓名")
    _ITEM_WORDS = (
        "物品",
        "道具",
        "兵器",
        "武器",
        "能力",
        "魔法",
        "技能",
        "装备",
        "宝物",
    )
    _ORGANIZATION_WORDS = (
        "组织",
        "团队",
        "成员",
        "势力",
        "公会",
        "教会",
        "军团",
        "家族",
        "公司",
        "学院",
    )

    def __init__(self, project: ProjectRepository) -> None:
        self.repository = NarrativeMemoryRepository(project)

    def cards_before(self, chapter_id: str) -> tuple[CanonContextCard, ...]:
        selected, conflicts = self._resolve(
            self.repository.list_canon_before(chapter_id)
        )
        facts_by_category: dict[CanonCardCategory, list[CanonCardFact]] = {
            category: [] for category in CanonCardCategory
        }
        conflicts_by_category: dict[CanonCardCategory, list[CanonCardConflict]] = {
            category: [] for category in CanonCardCategory
        }
        for entry in selected:
            facts_by_category[entry.category or self.category_for_title(entry.title)].append(
                CanonCardFact(
                    entry.id,
                    entry.title,
                    entry.detail,
                    entry.source_chapter_id,
                )
            )
        for conflict in conflicts:
            conflicts_by_category[
                conflict.category or self.category_for_title(conflict.title)
            ].append(conflict)

        cards: list[CanonContextCard] = []
        for category in CanonCardCategory:
            facts = tuple(facts_by_category[category])
            category_conflicts = tuple(conflicts_by_category[category])
            content = self._render(category, facts, category_conflicts)
            cards.append(
                CanonContextCard(
                    category=category,
                    title=category.display_title,
                    facts=facts,
                    conflicts=category_conflicts,
                    content=content,
                    content_hash=hashlib.sha256(content.encode("utf-8")).hexdigest(),
                )
            )
        return tuple(cards)

    @staticmethod
    def _resolve(
        entries: tuple[CanonEntry, ...],
    ) -> tuple[tuple[CanonEntry, ...], tuple[CanonCardConflict, ...]]:
        grouped: dict[str, list[CanonEntry]] = {}
        for entry in entries:
            grouped.setdefault(entry.title, []).append(entry)

        selected: list[CanonEntry] = []
        conflicts: list[CanonCardConflict] = []
        for title, versions in grouped.items():
            highest_rank = max(entry.authority.rank for entry in versions)
            candidates = [
                entry for entry in versions if entry.authority.rank == highest_rank
            ]
            details = tuple(dict.fromkeys(entry.detail for entry in candidates))
            if len(details) > 1:
                categories = {entry.category for entry in candidates if entry.category is not None}
                explicit_category = next(iter(categories)) if len(categories) == 1 else None
                conflicts.append(CanonCardConflict(title, details, explicit_category))
                continue
            selected.append(candidates[-1])
        return tuple(selected), tuple(conflicts)

    @classmethod
    def category_for_title(cls, title: str) -> CanonCardCategory:
        """Return the stable four-card category used by context and review UI."""
        if any(word in title for word in cls._CHARACTER_WORDS):
            return CanonCardCategory.CHARACTER_IDENTITY
        if any(word in title for word in cls._ITEM_WORDS):
            return CanonCardCategory.ITEM_ABILITY
        if any(word in title for word in cls._ORGANIZATION_WORDS):
            return CanonCardCategory.ORGANIZATION
        return CanonCardCategory.WORLD

    @staticmethod
    def category_for_display_title(display_title: str) -> CanonCardCategory:
        normalized = display_title.strip()
        for category in CanonCardCategory:
            if category.display_title == normalized:
                return category
        raise ValueError(f"未知正典卡片：{display_title}")

    @staticmethod
    def _render(
        category: CanonCardCategory,
        facts: tuple[CanonCardFact, ...],
        conflicts: tuple[CanonCardConflict, ...],
    ) -> str:
        if not facts and not conflicts:
            return ""
        lines = [f"【正典卡｜{category.display_title}】"]
        lines.extend(f"- {fact.title}：{fact.detail}" for fact in facts)
        lines.extend(
            f"- 【冲突待处理，不得作为确定正典】{conflict.title}："
            + "｜".join(conflict.details)
            for conflict in conflicts
        )
        return "\n".join(lines)
