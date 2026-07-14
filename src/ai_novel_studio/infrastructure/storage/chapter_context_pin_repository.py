from __future__ import annotations

import json
import sqlite3
from datetime import UTC, datetime

from ai_novel_studio.domain.context_pin import ChapterContextPin
from ai_novel_studio.domain.identifiers import new_id
from ai_novel_studio.infrastructure.storage.project_repository import ProjectRepository


class ChapterContextPinRepository:
    def __init__(self, project: ProjectRepository) -> None:
        self.project = project

    def add(
        self,
        *,
        chapter_id: str,
        source_type: str,
        source_id: str,
        context_category: str,
        title: str,
        content: str,
        source_chapter_id: str | None,
        source_revision: int | None,
        source_hash: str,
    ) -> ChapterContextPin:
        existing = self.find(chapter_id, source_type, source_id)
        if existing is not None:
            return existing
        pin = ChapterContextPin(
            new_id(),
            chapter_id,
            source_type.strip(),
            source_id.strip(),
            context_category,
            title.strip(),
            content.strip(),
            source_chapter_id,
            source_revision,
            source_hash,
            datetime.now(UTC),
        )
        with self.project.database.connect() as connection, connection:
            connection.execute(
                "INSERT INTO chapter_context_pins VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    pin.id,
                    pin.chapter_id,
                    pin.source_type,
                    pin.source_id,
                    pin.context_category,
                    pin.title,
                    pin.content,
                    pin.source_chapter_id,
                    pin.source_revision,
                    pin.source_hash,
                    pin.created_at.isoformat(),
                ),
            )
        return pin

    def list_for_chapter(self, chapter_id: str) -> tuple[ChapterContextPin, ...]:
        with self.project.database.connect() as connection:
            rows = connection.execute(
                "SELECT * FROM chapter_context_pins WHERE chapter_id = ? "
                "ORDER BY created_at, id",
                (chapter_id,),
            ).fetchall()
        return tuple(self._pin(row) for row in rows)

    def find(
        self, chapter_id: str, source_type: str, source_id: str
    ) -> ChapterContextPin | None:
        with self.project.database.connect() as connection:
            row = connection.execute(
                "SELECT * FROM chapter_context_pins WHERE chapter_id = ? "
                "AND source_type = ? AND source_id = ?",
                (chapter_id, source_type, source_id),
            ).fetchone()
        return self._pin(row) if row is not None else None

    def remove(self, chapter_id: str, source_type: str, source_id: str) -> bool:
        with self.project.database.connect() as connection, connection:
            cursor = connection.execute(
                "DELETE FROM chapter_context_pins WHERE chapter_id = ? "
                "AND source_type = ? AND source_id = ?",
                (chapter_id, source_type, source_id),
            )
        return cursor.rowcount == 1

    def source_chapter_ids(self, source_type: str, source_id: str) -> tuple[str, ...]:
        if source_type != "SUMMARY":
            return ()
        with self.project.database.connect() as connection:
            row = connection.execute(
                "SELECT source_chapter_ids_json FROM summary_nodes WHERE id = ?",
                (source_id,),
            ).fetchone()
        if row is None:
            return ()
        return tuple(str(value) for value in json.loads(row[0]))

    def is_before(self, source_chapter_id: str, target_chapter_id: str) -> bool:
        with self.project.database.connect() as connection:
            row = connection.execute(
                """
                SELECT CASE WHEN
                    source_volume.sort_index < target_volume.sort_index OR
                    (source_volume.sort_index = target_volume.sort_index AND
                     source_chapter.sort_index < target_chapter.sort_index)
                THEN 1 ELSE 0 END AS is_before
                FROM chapters source_chapter
                JOIN volumes source_volume ON source_volume.id = source_chapter.volume_id
                JOIN chapters target_chapter ON target_chapter.id = ?
                JOIN volumes target_volume ON target_volume.id = target_chapter.volume_id
                WHERE source_chapter.id = ?
                """,
                (target_chapter_id, source_chapter_id),
            ).fetchone()
        if row is None:
            raise KeyError("人工参考关联了不存在的章节")
        return bool(row[0])

    @staticmethod
    def _pin(row: sqlite3.Row) -> ChapterContextPin:
        return ChapterContextPin(
            row["id"],
            row["chapter_id"],
            row["source_type"],
            row["source_id"],
            row["context_category"],
            row["title"],
            row["content"],
            row["source_chapter_id"],
            row["source_revision"],
            row["source_hash"],
            datetime.fromisoformat(row["created_at"]),
        )
