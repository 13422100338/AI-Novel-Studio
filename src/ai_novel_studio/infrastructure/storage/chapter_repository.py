import hashlib
import os
import sqlite3
from datetime import UTC, datetime
from pathlib import Path

from ai_novel_studio.domain.chapter import Chapter, ChapterVersion
from ai_novel_studio.domain.identifiers import new_id, validate_id
from ai_novel_studio.infrastructure.storage.atomic_file import atomic_write_text
from ai_novel_studio.infrastructure.storage.project_repository import ProjectRepository


def _now() -> datetime:
    return datetime.now(UTC)


def _hash(content: str) -> str:
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


def _parse_time(value: str) -> datetime:
    return datetime.fromisoformat(value)


def _chapter_from_row(row: sqlite3.Row) -> Chapter:
    return Chapter(
        row["id"], row["volume_id"], row["declared_number"], row["title"],
        row["synopsis"], row["content_path"], row["sort_index"], row["revision"],
        row["memory_status"], bool(row["is_deleted"]), _parse_time(row["created_at"]),
        _parse_time(row["updated_at"]),
    )


class ChapterRepository:
    def __init__(self, project: ProjectRepository) -> None:
        self.project = project

    def create_chapter(
        self,
        volume_id: str,
        title: str,
        declared_number: str = "",
        content: str = "",
        synopsis: str = "",
    ) -> Chapter:
        validate_id(volume_id)
        if not title.strip():
            raise ValueError("chapter title cannot be empty")
        chapter_id = new_id()
        now = _now()
        relative = Path("manuscript") / f"volume_{volume_id}" / f"chapter_{chapter_id}.md"
        canonical = self.project.layout.root / relative
        atomic_write_text(canonical, content)
        connection = self.project.database.connect()
        try:
            with connection:
                exists = connection.execute("SELECT 1 FROM volumes WHERE id = ?", (volume_id,)).fetchone()
                if exists is None:
                    raise KeyError(f"unknown volume: {volume_id}")
                sort_index = int(
                    connection.execute(
                        "SELECT COALESCE(MAX(sort_index), -1) + 1 FROM chapters "
                        "WHERE volume_id = ? AND is_deleted = 0",
                        (volume_id,),
                    ).fetchone()[0]
                )
                connection.execute(
                    """
                    INSERT INTO chapters(
                        id, volume_id, declared_number, title, synopsis, content_path,
                        content_hash, sort_index, revision, memory_status, is_deleted,
                        deleted_content_path, created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 0, 'pending', 0, NULL, ?, ?)
                    """,
                    (
                        chapter_id, volume_id, declared_number, title.strip(), synopsis,
                        relative.as_posix(), _hash(content), sort_index, now.isoformat(), now.isoformat(),
                    ),
                )
        except BaseException:
            canonical.unlink(missing_ok=True)
            raise
        finally:
            connection.close()
        return self.get_chapter(chapter_id)

    def get_chapter(self, chapter_id: str, *, include_deleted: bool = True) -> Chapter:
        validate_id(chapter_id)
        connection = self.project.database.connect()
        try:
            query = "SELECT * FROM chapters WHERE id = ?"
            parameters: tuple[object, ...] = (chapter_id,)
            if not include_deleted:
                query += " AND is_deleted = 0"
            row = connection.execute(query, parameters).fetchone()
        finally:
            connection.close()
        if row is None:
            raise KeyError(f"unknown chapter: {chapter_id}")
        return _chapter_from_row(row)

    def list_chapters(self, volume_id: str | None = None) -> list[Chapter]:
        connection = self.project.database.connect()
        try:
            if volume_id is None:
                rows = connection.execute(
                    "SELECT * FROM chapters WHERE is_deleted = 0 ORDER BY volume_id, sort_index, id"
                ).fetchall()
            else:
                validate_id(volume_id)
                rows = connection.execute(
                    "SELECT * FROM chapters WHERE volume_id = ? AND is_deleted = 0 "
                    "ORDER BY sort_index, id",
                    (volume_id,),
                ).fetchall()
        finally:
            connection.close()
        return [_chapter_from_row(row) for row in rows]

    def read_content(self, chapter_id: str) -> str:
        chapter = self.get_chapter(chapter_id, include_deleted=False)
        return (self.project.layout.root / chapter.content_path).read_text(encoding="utf-8")

    def save_content(
        self, chapter_id: str, content: str, *, source: str, reason: str
    ) -> Chapter:
        chapter = self.get_chapter(chapter_id, include_deleted=False)
        canonical = self.project.layout.root / chapter.content_path
        previous = canonical.read_text(encoding="utf-8")
        version_id = new_id()
        snapshot_relative = (
            Path(".ai_pipeline") / "history" / chapter.id
            / f"revision_{chapter.revision}_{version_id}.md"
        )
        snapshot = self.project.layout.root / snapshot_relative
        atomic_write_text(snapshot, previous)
        atomic_write_text(canonical, content)
        now = _now()
        connection = self.project.database.connect()
        try:
            with connection:
                connection.execute(
                    """
                    INSERT INTO chapter_versions VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        version_id, chapter.id, chapter.revision, snapshot_relative.as_posix(),
                        source, reason, now.isoformat(), _hash(previous),
                    ),
                )
                cursor = connection.execute(
                    """
                    UPDATE chapters SET revision = revision + 1, content_hash = ?,
                    memory_status = 'stale', updated_at = ?
                    WHERE id = ? AND revision = ? AND is_deleted = 0
                    """,
                    (_hash(content), now.isoformat(), chapter.id, chapter.revision),
                )
                if cursor.rowcount != 1:
                    raise RuntimeError("chapter changed concurrently")
        except BaseException:
            atomic_write_text(canonical, previous)
            snapshot.unlink(missing_ok=True)
            raise
        finally:
            connection.close()
        return self.get_chapter(chapter.id)

    def list_versions(self, chapter_id: str) -> list[ChapterVersion]:
        validate_id(chapter_id)
        connection = self.project.database.connect()
        try:
            rows = connection.execute(
                "SELECT * FROM chapter_versions WHERE chapter_id = ? ORDER BY revision", (chapter_id,)
            ).fetchall()
        finally:
            connection.close()
        return [
            ChapterVersion(
                row["id"], row["chapter_id"], row["revision"], row["content_snapshot_path"],
                row["source"], row["reason"], _parse_time(row["created_at"]), row["content_hash"],
            )
            for row in rows
        ]

    def delete_chapter(self, chapter_id: str) -> None:
        chapter = self.get_chapter(chapter_id, include_deleted=False)
        canonical = self.project.layout.root / chapter.content_path
        trash_relative = Path(".ai_pipeline") / "trash" / f"chapter_{chapter.id}_r{chapter.revision}.md"
        trash = self.project.layout.root / trash_relative
        trash.parent.mkdir(parents=True, exist_ok=True)
        os.replace(canonical, trash)
        connection = self.project.database.connect()
        try:
            with connection:
                connection.execute(
                    "UPDATE chapters SET is_deleted = 1, deleted_content_path = ?, updated_at = ? "
                    "WHERE id = ?",
                    (trash_relative.as_posix(), _now().isoformat(), chapter.id),
                )
        except BaseException:
            canonical.parent.mkdir(parents=True, exist_ok=True)
            os.replace(trash, canonical)
            raise
        finally:
            connection.close()

    def restore_chapter(self, chapter_id: str) -> Chapter:
        chapter = self.get_chapter(chapter_id)
        if not chapter.is_deleted:
            return chapter
        connection = self.project.database.connect()
        try:
            row = connection.execute(
                "SELECT deleted_content_path FROM chapters WHERE id = ?", (chapter.id,)
            ).fetchone()
            if row is None or not row["deleted_content_path"]:
                raise RuntimeError("deleted chapter has no trash location")
            trash = self.project.layout.root / row["deleted_content_path"]
            canonical = self.project.layout.root / chapter.content_path
            canonical.parent.mkdir(parents=True, exist_ok=True)
            os.replace(trash, canonical)
            try:
                with connection:
                    connection.execute(
                        "UPDATE chapters SET is_deleted = 0, deleted_content_path = NULL, updated_at = ? "
                        "WHERE id = ?",
                        (_now().isoformat(), chapter.id),
                    )
            except BaseException:
                os.replace(canonical, trash)
                raise
        finally:
            connection.close()
        return self.get_chapter(chapter.id)

    def delete_volume(self, volume_id: str, target_volume_id: str) -> None:
        validate_id(volume_id)
        validate_id(target_volume_id)
        if volume_id == target_volume_id:
            raise ValueError("target volume must be different from deleted volume")
        moving = self.list_chapters(volume_id)
        moved_paths: list[tuple[Path, Path]] = []
        connection = self.project.database.connect()
        try:
            with connection:
                target_exists = connection.execute(
                    "SELECT 1 FROM volumes WHERE id = ?", (target_volume_id,)
                ).fetchone()
                source_exists = connection.execute("SELECT 1 FROM volumes WHERE id = ?", (volume_id,)).fetchone()
                if target_exists is None or source_exists is None:
                    raise KeyError("source or target volume does not exist")
                next_index = int(
                    connection.execute(
                        "SELECT COALESCE(MAX(sort_index), -1) + 1 FROM chapters "
                        "WHERE volume_id = ? AND is_deleted = 0", (target_volume_id,),
                    ).fetchone()[0]
                )
                for offset, chapter in enumerate(moving):
                    old_path = self.project.layout.root / chapter.content_path
                    new_relative = (
                        Path("manuscript") / f"volume_{target_volume_id}" / f"chapter_{chapter.id}.md"
                    )
                    new_path = self.project.layout.root / new_relative
                    new_path.parent.mkdir(parents=True, exist_ok=True)
                    os.replace(old_path, new_path)
                    moved_paths.append((old_path, new_path))
                    connection.execute(
                        "UPDATE chapters SET volume_id = ?, content_path = ?, sort_index = ?, updated_at = ? "
                        "WHERE id = ?",
                        (
                            target_volume_id, new_relative.as_posix(), next_index + offset,
                            _now().isoformat(), chapter.id,
                        ),
                    )
                connection.execute("DELETE FROM volumes WHERE id = ?", (volume_id,))
        except BaseException:
            for old_path, new_path in reversed(moved_paths):
                old_path.parent.mkdir(parents=True, exist_ok=True)
                if new_path.exists():
                    os.replace(new_path, old_path)
            raise
        finally:
            connection.close()
