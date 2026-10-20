import os
from pathlib import Path

from ai_novel_studio.core.outline_links import (
    chapter_markdown_link,
    insert_chapter_link,
    registered_chapter_path,
)
from ai_novel_studio.domain.outline import OutlineSnapshot, outline_content_hash
from ai_novel_studio.infrastructure.storage.chapter_repository import ChapterRepository
from ai_novel_studio.infrastructure.storage.outline_link_repository import OutlineLinkRepository
from ai_novel_studio.infrastructure.storage.outline_repository import (
    OutlineConflictError,
    OutlineRepository,
    read_outline_text,
)


class OutlineService:
    """Author-driven outline import, reimport and version restoration."""

    def __init__(self, outlines: OutlineRepository) -> None:
        self.outlines = outlines
        self.links = OutlineLinkRepository(outlines.project)

    def propose_chapter_link(
        self, document_id: str, chapter_id: str, line: int, *, expected_revision: int
    ) -> str:
        snapshot = self.outlines.read(document_id)
        if snapshot.version.revision != expected_revision:
            raise OutlineConflictError("大纲已变更，请重新选择关联位置")
        project = self.outlines.project
        chapter = ChapterRepository(project).get_chapter(chapter_id, include_deleted=False)
        if registered_chapter_path(project.layout.root, chapter.content_path) is None:
            raise ValueError("章节路径无效")
        return insert_chapter_link(
            snapshot.content, line, chapter_markdown_link(chapter.title, chapter.content_path)
        )

    def import_file(self, source: Path, *, title: str | None = None) -> OutlineSnapshot:
        content = self._source_text(source)
        return self.outlines.create(source.stem if title is None else title, content)

    def reimport_file(
        self, document_id: str, source: Path, *, expected_revision: int
    ) -> OutlineSnapshot:
        content = self._source_text(source)
        return self.outlines.save(document_id, content, expected_revision=expected_revision)

    def restore_version(
        self, document_id: str, revision: int, *, expected_revision: int
    ) -> OutlineSnapshot:
        previous = self.outlines.read_version(document_id, revision)
        return self.outlines.save(
            document_id, previous.content, expected_revision=expected_revision
        )

    @staticmethod
    def preview_file(source: Path) -> str:
        return OutlineService._source_text(source)

    @staticmethod
    def export_text(content: str, destination: Path) -> None:
        outline_content_hash(content)
        if destination.suffix.casefold() not in {".md", ".markdown", ".txt"}:
            raise ValueError("请导出为 Markdown 或文本文件")
        with destination.open("xb") as stream:
            stream.write(content.encode("utf-8"))
            stream.flush()
            os.fsync(stream.fileno())

    @staticmethod
    def _source_text(source: Path) -> str:
        if source.suffix.casefold() not in {".md", ".markdown", ".txt"}:
            raise ValueError("请选择 UTF-8 Markdown 或文本大纲")
        return read_outline_text(source)
