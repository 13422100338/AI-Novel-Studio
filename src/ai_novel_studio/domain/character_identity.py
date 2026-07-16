from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum


class CharacterMergeStatus(StrEnum):
    APPLIED = "APPLIED"
    REVERSED = "REVERSED"


@dataclass(frozen=True, slots=True)
class MovedBriefReference:
    id: str
    revision_after: int
    content_hash_after: str

    def __post_init__(self) -> None:
        if not self.id.strip():
            raise ValueError("Brief ID 不能为空")
        if self.revision_after < 0:
            raise ValueError("Brief 修订号不能为负数")
        if not self.content_hash_after.strip():
            raise ValueError("Brief 内容哈希不能为空")


@dataclass(frozen=True, slots=True)
class CharacterIdentityMerge:
    id: str
    source_character_id: str
    target_character_id: str
    source_canonical_name: str
    source_aliases: tuple[str, ...]
    target_aliases_before: tuple[str, ...]
    target_aliases_after: tuple[str, ...]
    moved_state_event_ids: tuple[str, ...]
    moved_knowledge_event_ids: tuple[str, ...]
    moved_briefs: tuple[MovedBriefReference, ...]
    reason: str
    status: CharacterMergeStatus
    created_at: datetime
    reversed_at: datetime | None

    def __post_init__(self) -> None:
        for field, value in (
            ("归并 ID", self.id),
            ("来源人物 ID", self.source_character_id),
            ("目标人物 ID", self.target_character_id),
            ("来源人物名称", self.source_canonical_name),
            ("归并原因", self.reason),
        ):
            if not value.strip():
                raise ValueError(f"{field}不能为空")
        if self.source_character_id == self.target_character_id:
            raise ValueError("不能把同一张人物卡归并到自身")
        if self.status == CharacterMergeStatus.APPLIED and self.reversed_at is not None:
            raise ValueError("尚未撤销的归并不能包含撤销时间")
        if self.status == CharacterMergeStatus.REVERSED and self.reversed_at is None:
            raise ValueError("已撤销的归并必须包含撤销时间")
        for values in (
            self.source_aliases,
            self.target_aliases_before,
            self.target_aliases_after,
            self.moved_state_event_ids,
            self.moved_knowledge_event_ids,
        ):
            if len(values) != len(tuple(dict.fromkeys(values))):
                raise ValueError("人物归并记录不能包含重复值")

    @property
    def moved_brief_ids(self) -> tuple[str, ...]:
        return tuple(item.id for item in self.moved_briefs)
