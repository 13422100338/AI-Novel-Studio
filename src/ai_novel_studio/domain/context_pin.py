from dataclasses import dataclass
from datetime import datetime

from ai_novel_studio.domain.identifiers import validate_id


@dataclass(frozen=True, slots=True)
class ChapterContextPin:
    id: str
    chapter_id: str
    source_type: str
    source_id: str
    context_category: str
    title: str
    content: str
    source_chapter_id: str | None
    source_revision: int | None
    source_hash: str
    created_at: datetime

    def __post_init__(self) -> None:
        validate_id(self.id)
        validate_id(self.chapter_id)
        if not self.source_type.strip() or not self.source_id.strip():
            raise ValueError("人工参考来源不能为空")
        if self.context_category not in {"MEMORY", "HISTORY"}:
            raise ValueError("人工参考类别无效")
        if not self.title.strip() or not self.content.strip():
            raise ValueError("人工参考标题和内容不能为空")
        if self.source_revision is not None and self.source_revision < 0:
            raise ValueError("人工参考来源修订不能为负数")
