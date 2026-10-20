from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from ai_novel_studio.domain.chapter import Chapter
from ai_novel_studio.domain.identifiers import validate_id
from ai_novel_studio.domain.outline import validate_outline_hash


@dataclass(frozen=True, slots=True)
class OutlineLinkReview:
    action: str
    fingerprint: str
    source_revision: int
    source_line: int
    source_column: int
    source_hash: str
    created_at: datetime

    def __post_init__(self) -> None:
        if self.action not in {"DISCOVERED", "CONFIRMED", "RELOCATED", "REMOVED"}:
            raise ValueError("invalid outline link review")
        validate_outline_hash(self.fingerprint)
        validate_outline_hash(self.source_hash)
        if self.source_revision < 1 or self.source_line < 1 or self.source_column < 0:
            raise ValueError("invalid outline link source")


@dataclass(frozen=True, slots=True)
class OutlineChapterLink:
    id: str
    document_id: str
    chapter_id: str
    chapter_title: str
    source_revision: int
    source_line: int
    source_column: int
    source_quote: str
    confirmed_fingerprint: str | None
    active: bool
    reviews: tuple[OutlineLinkReview, ...]

    def __post_init__(self) -> None:
        for value in (self.id, self.document_id, self.chapter_id):
            validate_id(value)
        if self.confirmed_fingerprint is not None:
            validate_outline_hash(self.confirmed_fingerprint)
        if self.source_revision < 1 or self.source_line < 1 or self.source_column < 0:
            raise ValueError("invalid outline link source")
        if not self.source_quote or any(c in self.source_quote for c in "\x00\r\n"):
            raise ValueError("invalid outline link quote")


@dataclass(frozen=True, slots=True)
class OutlineLinkItem:
    link: OutlineChapterLink
    status: str
    line: int | None
    column: int | None
    position: int | None
    section_title: str
    chapter_title: str


@dataclass(frozen=True, slots=True)
class OutlineLinkSnapshot:
    fingerprint: str
    source_revision: int
    source_hash: str
    items: tuple[OutlineLinkItem, ...]
    pending_total: int
    chapters: tuple[Chapter, ...]
