from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum


class Authority(StrEnum):
    USER_CONFIRMED = "USER_CONFIRMED"
    OUTLINE = "OUTLINE"
    AUDITED = "AUDITED"
    MODEL_EXTRACTED = "MODEL_EXTRACTED"
    INFERRED = "INFERRED"

    @property
    def rank(self) -> int:
        return {
            Authority.USER_CONFIRMED: 50,
            Authority.OUTLINE: 40,
            Authority.AUDITED: 30,
            Authority.MODEL_EXTRACTED: 20,
            Authority.INFERRED: 10,
        }[self]


class ReviewStatus(StrEnum):
    REVIEW = "REVIEW"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    LOCKED = "LOCKED"


class MemoryStatus(StrEnum):
    CURRENT = "CURRENT"
    STALE = "STALE"
    REBUILDING = "REBUILDING"
    REVIEW = "REVIEW"
    FAILED = "FAILED"


class SourceType(StrEnum):
    HUMAN = "HUMAN"
    MODEL = "MODEL"
    IMPORT = "IMPORT"
    SYSTEM = "SYSTEM"


class KnowledgeSubject(StrEnum):
    CHARACTER = "CHARACTER"
    READER = "READER"


class KnowledgeState(StrEnum):
    UNKNOWN = "UNKNOWN"
    SUSPECTED = "SUSPECTED"
    MISUNDERSTOOD = "MISUNDERSTOOD"
    KNOWN = "KNOWN"
    FORGOTTEN = "FORGOTTEN"


class ClueType(StrEnum):
    FORESHADOW = "FORESHADOW"
    MISDIRECTION = "MISDIRECTION"
    OPEN_QUESTION = "OPEN_QUESTION"
    AUTHOR_PROMISE = "AUTHOR_PROMISE"
    ATMOSPHERIC_HINT = "ATMOSPHERIC_HINT"


class ClueAction(StrEnum):
    PLANT = "PLANT"
    REINFORCE = "REINFORCE"
    REDIRECT = "REDIRECT"
    REVEAL = "REVEAL"
    RESOLVE = "RESOLVE"
    ABANDON = "ABANDON"


class SummaryLevel(StrEnum):
    RAW = "L0"
    CHAPTER = "L1"
    ARC = "L2"
    VOLUME = "L3"
    BOOK = "L4"


class StyleScope(StrEnum):
    BOOK = "BOOK"
    GENRE_OR_SCENE = "GENRE_OR_SCENE"
    CHARACTER = "CHARACTER"
    CHAPTER = "CHAPTER"


def _required(value: str, field: str) -> str:
    normalized = value.strip()
    if not normalized:
        raise ValueError(f"{field}不能为空")
    return normalized


def _confidence(value: float) -> float:
    if not 0 <= value <= 1:
        raise ValueError("confidence 必须在 0 到 1 之间")
    return value


@dataclass(frozen=True, slots=True)
class Character:
    id: str
    canonical_name: str
    aliases: tuple[str, ...]
    profile: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "id", _required(self.id, "人物 ID"))
        object.__setattr__(
            self, "canonical_name", _required(self.canonical_name, "人物名称")
        )
        aliases = tuple(dict.fromkeys(alias.strip() for alias in self.aliases if alias.strip()))
        object.__setattr__(self, "aliases", aliases)


@dataclass(frozen=True, slots=True)
class CharacterStateEvent:
    id: str
    character_id: str
    chapter_id: str
    motivation: str
    psychology: str
    current_goal: str
    relationships: str
    recent_activity: str
    confidence: float
    source_type: SourceType
    review_status: ReviewStatus
    created_at: datetime

    def __post_init__(self) -> None:
        _required(self.id, "状态 ID")
        _required(self.character_id, "人物 ID")
        _required(self.chapter_id, "章节 ID")
        _confidence(self.confidence)


@dataclass(frozen=True, slots=True)
class KnowledgeItem:
    id: str
    title: str
    detail: str
    authority: Authority
    review_status: ReviewStatus


@dataclass(frozen=True, slots=True)
class KnowledgeStateEvent:
    id: str
    knowledge_id: str
    subject_type: KnowledgeSubject
    subject_id: str
    chapter_id: str
    state: KnowledgeState
    evidence: str
    source_type: SourceType
    review_status: ReviewStatus
    created_at: datetime


@dataclass(frozen=True, slots=True)
class CanonEntry:
    id: str
    title: str
    detail: str
    source_chapter_id: str | None
    source_paragraph_id: str | None
    confidence: float
    authority: Authority
    status: MemoryStatus
    review_status: ReviewStatus
    created_at: datetime

    def __post_init__(self) -> None:
        _confidence(self.confidence)


@dataclass(frozen=True, slots=True)
class NarrativeClue:
    id: str
    clue_type: ClueType
    title: str
    detail: str
    authority: Authority
    status: MemoryStatus
    review_status: ReviewStatus
    created_at: datetime


@dataclass(frozen=True, slots=True)
class NarrativeClueEvent:
    id: str
    clue_id: str
    chapter_id: str
    action: ClueAction
    detail: str
    source_type: SourceType
    review_status: ReviewStatus
    created_at: datetime


@dataclass(frozen=True, slots=True)
class SummaryNode:
    id: str
    level: SummaryLevel
    scope_id: str
    content: str
    source_chapter_ids: tuple[str, ...]
    source_revisions: tuple[tuple[str, int, str], ...]
    content_hash: str
    model_profile_id: str | None
    authority: Authority
    review_status: ReviewStatus
    status: MemoryStatus
    revision: int
    created_at: datetime


@dataclass(frozen=True, slots=True)
class StyleRule:
    id: str
    scope_type: StyleScope
    scope_id: str
    rule_type: str
    rule_text: str
    limit_per_chapter: int | None
    limit_per_volume: int | None
    limit_per_book: int | None
    authority: Authority
    review_status: ReviewStatus
    status: MemoryStatus


@dataclass(frozen=True, slots=True)
class StyleSample:
    id: str
    scope_type: StyleScope
    scope_id: str
    title: str
    content: str
    source_type: SourceType
    authority: Authority
    review_status: ReviewStatus
    immutable: bool
    content_hash: str


@dataclass(frozen=True, slots=True)
class MemoryDependency:
    id: str
    memory_type: str
    memory_id: str
    source_chapter_id: str
    source_revision: int
    source_hash: str
    status: MemoryStatus
