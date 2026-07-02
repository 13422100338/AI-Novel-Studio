from dataclasses import dataclass
from datetime import datetime

from ai_novel_studio.domain.identifiers import validate_id


@dataclass(frozen=True, slots=True)
class Project:
    id: str
    title: str
    format_version: int
    created_at: datetime
    updated_at: datetime

    def __post_init__(self) -> None:
        validate_id(self.id)
        if not self.title.strip():
            raise ValueError("project title cannot be empty")
        if self.format_version < 1:
            raise ValueError("format version must be positive")
