from __future__ import annotations

import hashlib
import sqlite3
from datetime import UTC, datetime

from ai_novel_studio.domain.generation import ChapterRequirement
from ai_novel_studio.domain.identifiers import new_id
from ai_novel_studio.infrastructure.storage.project_repository import ProjectRepository


class StaleRequirementError(RuntimeError):
    pass


def _now() -> datetime:
    return datetime.now(UTC)


def _hash(content: str) -> str:
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


class ChapterRequirementRepository:
    def __init__(self, project: ProjectRepository) -> None:
        self.project = project

    def get_or_create(self, chapter_id: str) -> ChapterRequirement:
        now = _now()
        with self.project.database.connect() as connection, connection:
            chapter = connection.execute(
                "SELECT id FROM chapters WHERE id = ? AND is_deleted = 0", (chapter_id,)
            ).fetchone()
            if chapter is None:
                raise KeyError(f"unknown active chapter: {chapter_id}")
            connection.execute(
                """
                INSERT INTO chapter_requirements
                    (id, chapter_id, content, is_locked, revision, content_hash,
                     created_at, updated_at)
                VALUES (?, ?, '', 0, 0, ?, ?, ?)
                ON CONFLICT(chapter_id) DO NOTHING
                """,
                (new_id(), chapter_id, _hash(""), now.isoformat(), now.isoformat()),
            )
            row = connection.execute(
                "SELECT * FROM chapter_requirements WHERE chapter_id = ?", (chapter_id,)
            ).fetchone()
        if row is None:
            raise RuntimeError("chapter requirement creation did not produce a row")
        return self._requirement(row)

    def get(self, chapter_id: str) -> ChapterRequirement:
        with self.project.database.connect() as connection:
            row = connection.execute(
                "SELECT * FROM chapter_requirements WHERE chapter_id = ?", (chapter_id,)
            ).fetchone()
        if row is None:
            raise KeyError(f"unknown chapter requirement: {chapter_id}")
        return self._requirement(row)

    def update(
        self,
        chapter_id: str,
        content: str,
        *,
        is_locked: bool,
        expected_revision: int,
    ) -> ChapterRequirement:
        now = _now().isoformat()
        with self.project.database.connect() as connection, connection:
            cursor = connection.execute(
                """
                UPDATE chapter_requirements
                SET content = ?, is_locked = ?, revision = revision + 1,
                    content_hash = ?, updated_at = ?
                WHERE chapter_id = ? AND revision = ?
                """,
                (
                    content,
                    int(is_locked),
                    _hash(content),
                    now,
                    chapter_id,
                    expected_revision,
                ),
            )
            if cursor.rowcount != 1:
                exists = connection.execute(
                    "SELECT 1 FROM chapter_requirements WHERE chapter_id = ?", (chapter_id,)
                ).fetchone()
                if exists is None:
                    raise KeyError(f"unknown chapter requirement: {chapter_id}")
                raise StaleRequirementError(
                    f"章节要求修订已变化，提交修订为 {expected_revision}"
                )
        return self.get(chapter_id)

    @staticmethod
    def _requirement(row: sqlite3.Row) -> ChapterRequirement:
        return ChapterRequirement(
            row["id"],
            row["chapter_id"],
            row["content"],
            bool(row["is_locked"]),
            int(row["revision"]),
            row["content_hash"],
            datetime.fromisoformat(row["created_at"]),
            datetime.fromisoformat(row["updated_at"]),
        )
