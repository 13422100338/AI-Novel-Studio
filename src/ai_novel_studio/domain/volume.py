from dataclasses import dataclass
from datetime import datetime

from ai_novel_studio.domain.identifiers import validate_id


@dataclass(frozen=True, slots=True)
class Volume:
    id: str
    title: str
    synopsis: str
    sort_index: int
    created_at: datetime
    updated_at: datetime

    def __post_init__(self) -> None:
        validate_id(self.id)
        if not self.title.strip():
            raise ValueError("volume title cannot be empty")
        if self.sort_index < 0:
            raise ValueError("volume sort index cannot be negative")
