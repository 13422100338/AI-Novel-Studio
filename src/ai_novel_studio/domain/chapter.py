from dataclasses import dataclass
from datetime import datetime

from ai_novel_studio.domain.identifiers import validate_id


@dataclass(frozen=True, slots=True)
class Chapter:
    id: str
    volume_id: str
    declared_number: str
    title: str
    synopsis: str
    content_path: str
    sort_index: int
    revision: int
    memory_status: str
    is_deleted: bool
    created_at: datetime
    updated_at: datetime

    def __post_init__(self) -> None:
        validate_id(self.id)
        validate_id(self.volume_id)
        if not self.title.strip():
            raise ValueError("chapter title cannot be empty")
        if self.sort_index < 0 or self.revision < 0:
            raise ValueError("chapter indexes cannot be negative")


@dataclass(frozen=True, slots=True)
class ChapterVersion:
    id: str
    chapter_id: str
    revision: int
    content_snapshot_path: str
    source: str
    reason: str
    created_at: datetime
    content_hash: str

    def __post_init__(self) -> None:
        validate_id(self.id)
        validate_id(self.chapter_id)
        if self.revision < 0:
            raise ValueError("revision cannot be negative")
