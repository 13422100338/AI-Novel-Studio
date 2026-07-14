from __future__ import annotations

from ai_novel_studio.application.memory_workspace_service import MemoryWorkspaceRecord
from ai_novel_studio.domain.context_pin import ChapterContextPin
from ai_novel_studio.domain.memory import MemoryStatus, ReviewStatus
from ai_novel_studio.infrastructure.storage.chapter_context_pin_repository import (
    ChapterContextPinRepository,
)


class ChapterContextPinService:
    def __init__(self, repository: ChapterContextPinRepository) -> None:
        self.repository = repository

    def list_for_chapter(self, chapter_id: str) -> tuple[ChapterContextPin, ...]:
        return self.repository.list_for_chapter(chapter_id)

    def pin(self, chapter_id: str, record: MemoryWorkspaceRecord) -> ChapterContextPin:
        if record.review_status not in {ReviewStatus.APPROVED, ReviewStatus.LOCKED}:
            raise PermissionError("待审查记忆必须先晋升，才能加入正文参考")
        if record.status != MemoryStatus.CURRENT:
            raise PermissionError("只有当前有效的记忆才能加入正文参考")
        source_chapters = self.repository.source_chapter_ids(
            record.source_type, record.id
        ) or ((record.source_chapter_id,) if record.source_chapter_id else ())
        if any(
            not self.repository.is_before(source_id, chapter_id)
            for source_id in source_chapters
        ):
            raise PermissionError("不能把当前章或未来章节的记忆加入本章参考")
        return self.repository.add(
            chapter_id=chapter_id,
            source_type=record.source_type,
            source_id=record.id,
            context_category=(
                "HISTORY" if record.source_type == "SUMMARY" else "MEMORY"
            ),
            title=record.title,
            content=record.content,
            source_chapter_id=record.source_chapter_id,
            source_revision=record.source_revision,
            source_hash=record.source_hash,
        )

    def unpin(self, chapter_id: str, record: MemoryWorkspaceRecord) -> bool:
        return self.repository.remove(chapter_id, record.source_type, record.id)

    def is_pinned(self, chapter_id: str, record: MemoryWorkspaceRecord) -> bool:
        return (
            self.repository.find(chapter_id, record.source_type, record.id) is not None
        )

    def pin_compressed_history(
        self,
        chapter_id: str,
        records: tuple[MemoryWorkspaceRecord, ...],
    ) -> tuple[ChapterContextPin, ...]:
        pinned: list[ChapterContextPin] = []
        for record in records:
            if record.source_type != "SUMMARY":
                continue
            if self.is_pinned(chapter_id, record):
                continue
            try:
                pinned.append(self.pin(chapter_id, record))
            except PermissionError:
                continue
        return tuple(pinned)
