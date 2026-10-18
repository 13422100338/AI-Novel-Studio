import hashlib
import os
import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from ai_novel_studio.domain.chapter import Chapter, ChapterVersion
from ai_novel_studio.domain.identifiers import new_id, validate_id
from ai_novel_studio.infrastructure.storage.atomic_file import atomic_write_text
from ai_novel_studio.infrastructure.storage.memory_dependency_repository import (
    MemoryDependencyRepository,
)
from ai_novel_studio.infrastructure.storage.occurrence_repository import (
    OccurrenceRepository,
)
from ai_novel_studio.infrastructure.storage.project_repository import ProjectRepository
from ai_novel_studio.infrastructure.storage.view_assertion_repository import (
    ViewAssertionRepository,
)

_METADATA_CHANGE_SOURCE = "metadata_change"
_CHAPTER_TITLE_CHANGE_REASON = "chapter title changed"
_CHAPTER_RELOCATION_REASON = "chapter relocated by volume deletion"


class StaleChapterRevisionError(RuntimeError):
    pass


class ChapterFileRollbackError(RuntimeError):
    pass


class ChapterFileTransaction:
    """Same-process file rollback state; process-crash recovery is out of scope."""

    def __init__(self) -> None:
        self._actions: list[tuple[Path, str | None]] = []

    def checkpoint(self) -> int:
        return len(self._actions)

    def register_created_file(self, path: Path) -> None:
        self._actions.append((path, None))

    def register_replaced_text(self, path: Path, previous: str) -> None:
        self._actions.append((path, previous))

    def rollback_to(self, checkpoint: int) -> None:
        if not 0 <= checkpoint <= len(self._actions):
            raise ValueError("chapter file rollback checkpoint is invalid")
        failures = 0
        for path, previous in reversed(self._actions[checkpoint:]):
            try:
                if previous is None:
                    path.unlink(missing_ok=True)
                else:
                    atomic_write_text(path, previous)
            except (OSError, UnicodeError):
                failures += 1
        del self._actions[checkpoint:]
        if failures:
            raise ChapterFileRollbackError("chapter file rollback requires manual recovery")

    def rollback(self) -> None:
        self.rollback_to(0)

    def finalize(self) -> None:
        self._actions.clear()


@dataclass(frozen=True, slots=True)
class ChapterRelocationExpectation:
    chapter_id: str
    revision: int
    content_hash: str

    def __post_init__(self) -> None:
        validate_id(self.chapter_id)
        if (
            isinstance(self.revision, bool)
            or not isinstance(self.revision, int)
            or self.revision < 0
        ):
            raise ValueError("chapter relocation revision is invalid")
        if (
            not isinstance(self.content_hash, str)
            or len(self.content_hash) != 64
            or any(character not in "0123456789abcdef" for character in self.content_hash)
        ):
            raise ValueError("chapter relocation content hash is invalid")


def _now() -> datetime:
    return datetime.now(UTC)


def _hash(content: str) -> str:
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


def _parse_time(value: str) -> datetime:
    return datetime.fromisoformat(value)


def _chapter_from_row(row: sqlite3.Row) -> Chapter:
    return Chapter(
        row["id"],
        row["volume_id"],
        row["declared_number"],
        row["title"],
        row["synopsis"],
        row["content_path"],
        row["sort_index"],
        row["revision"],
        row["memory_status"],
        bool(row["is_deleted"]),
        _parse_time(row["created_at"]),
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
                exists = connection.execute(
                    "SELECT 1 FROM volumes WHERE id = ?", (volume_id,)
                ).fetchone()
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
                        chapter_id,
                        volume_id,
                        declared_number,
                        title.strip(),
                        synopsis,
                        relative.as_posix(),
                        _hash(content),
                        sort_index,
                        now.isoformat(),
                        now.isoformat(),
                    ),
                )
        except BaseException:
            canonical.unlink(missing_ok=True)
            raise
        finally:
            connection.close()
        return self.get_chapter(chapter_id)

    def get_chapter(
        self,
        chapter_id: str,
        *,
        include_deleted: bool = True,
        connection: sqlite3.Connection | None = None,
    ) -> Chapter:
        validate_id(chapter_id)
        if connection is not None:
            return self._get_chapter(
                connection,
                chapter_id,
                include_deleted=include_deleted,
            )
        owned = self.project.database.connect()
        try:
            return self._get_chapter(
                owned,
                chapter_id,
                include_deleted=include_deleted,
            )
        finally:
            owned.close()

    @staticmethod
    def _get_chapter(
        connection: sqlite3.Connection,
        chapter_id: str,
        *,
        include_deleted: bool,
    ) -> Chapter:
        query = "SELECT * FROM chapters WHERE id = ?"
        parameters: tuple[object, ...] = (chapter_id,)
        if not include_deleted:
            query += " AND is_deleted = 0"
        row = connection.execute(query, parameters).fetchone()
        if row is None:
            raise KeyError(f"unknown chapter: {chapter_id}")
        return _chapter_from_row(row)

    def list_chapters(self, volume_id: str | None = None) -> list[Chapter]:
        connection = self.project.database.connect()
        try:
            if volume_id is None:
                rows = connection.execute(
                    "SELECT c.* FROM chapters c "
                    "JOIN volumes v ON v.id = c.volume_id "
                    "WHERE c.is_deleted = 0 "
                    "ORDER BY v.sort_index, c.sort_index, c.id"
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

    def get_chapter_sequences(self) -> dict[str, int]:
        """Return one-based sequences for all non-deleted chapters in book order."""
        return {
            chapter.id: sequence for sequence, chapter in enumerate(self.list_chapters(), start=1)
        }

    def get_chapter_sequence(self, chapter_id: str) -> int:
        """Return the one-based sequence of a non-deleted chapter in book order."""
        validate_id(chapter_id)
        sequences = self.get_chapter_sequences()
        try:
            return sequences[chapter_id]
        except KeyError as error:
            raise KeyError(f"unknown or deleted chapter: {chapter_id}") from error

    def list_before(self, chapter_id: str) -> list[Chapter]:
        """Return non-deleted chapters before the target in canonical book order."""
        validate_id(chapter_id)
        with self.project.database.connect() as connection:
            rows = connection.execute(
                """
                WITH target AS (
                    SELECT c.id AS chapter_id,
                           v.sort_index AS volume_order,
                           c.sort_index AS chapter_order
                    FROM chapters c
                    JOIN volumes v ON v.id = c.volume_id
                    WHERE c.id = ? AND c.is_deleted = 0
                )
                SELECT c.*
                FROM chapters c
                JOIN volumes v ON v.id = c.volume_id
                CROSS JOIN target t
                WHERE c.is_deleted = 0
                  AND (
                    v.sort_index < t.volume_order
                    OR (
                        v.sort_index = t.volume_order
                        AND (
                            c.sort_index < t.chapter_order
                            OR (
                                c.sort_index = t.chapter_order
                                AND c.id < t.chapter_id
                            )
                        )
                    )
                  )
                ORDER BY v.sort_index, c.sort_index, c.id
                """,
                (chapter_id,),
            ).fetchall()
        return [_chapter_from_row(row) for row in rows]

    def read_content(self, chapter_id: str) -> str:
        chapter = self.get_chapter(chapter_id, include_deleted=False)
        return (self.project.layout.root / chapter.content_path).read_text(encoding="utf-8")

    def read_content_exact(
        self,
        chapter_id: str,
        *,
        connection: sqlite3.Connection | None = None,
    ) -> str:
        chapter = self.get_chapter(
            chapter_id,
            include_deleted=False,
            connection=connection,
        )
        return self._read_content_path_exact(chapter.content_path)

    def _resolve_manuscript_path(self, content_path: str | Path) -> Path:
        manuscript_root = self.project.layout.manuscript.resolve()
        source_path = (self.project.layout.root / content_path).resolve()
        try:
            source_path.relative_to(manuscript_root)
        except ValueError as error:
            raise RuntimeError("chapter source path is outside manuscript directory") from error
        return source_path

    def _read_content_path_exact(self, content_path: str | Path) -> str:
        source_path = self._resolve_manuscript_path(content_path)
        if not source_path.is_file():
            raise RuntimeError("chapter source file is missing")
        try:
            with source_path.open("r", encoding="utf-8", newline="") as stream:
                return stream.read()
        except (OSError, UnicodeError):
            raise RuntimeError("chapter source file cannot be read as UTF-8") from None

    def rename_chapter(
        self,
        chapter_id: str,
        title: str,
        *,
        expected_revision: int | None = None,
        connection: sqlite3.Connection | None = None,
        file_transaction: ChapterFileTransaction | None = None,
    ) -> Chapter:
        if connection is None:
            if file_transaction is not None:
                raise ValueError("chapter file transaction requires a connection")
            owned = self.project.database.connect()
            local_files = ChapterFileTransaction()
            try:
                owned.execute("BEGIN IMMEDIATE")
                chapter = self._rename_chapter(
                    owned,
                    local_files,
                    chapter_id,
                    title,
                    expected_revision=expected_revision,
                )
                owned.commit()
            except BaseException:
                owned.rollback()
                local_files.rollback()
                raise
            else:
                local_files.finalize()
                return chapter
            finally:
                owned.close()
        if file_transaction is None:
            raise ValueError("caller connection requires a chapter file transaction")
        return self._rename_chapter(
            connection,
            file_transaction,
            chapter_id,
            title,
            expected_revision=expected_revision,
        )

    def _rename_chapter(
        self,
        connection: sqlite3.Connection,
        file_transaction: ChapterFileTransaction,
        chapter_id: str,
        title: str,
        *,
        expected_revision: int | None,
    ) -> Chapter:
        chapter = self.get_chapter(
            chapter_id,
            include_deleted=False,
            connection=connection,
        )
        if expected_revision is not None and chapter.revision != expected_revision:
            raise StaleChapterRevisionError(
                "chapter revision changed: "
                f"expected {expected_revision}, current {chapter.revision}"
            )
        normalized = title.strip()
        if not normalized:
            raise ValueError("chapter title cannot be empty")
        if normalized == chapter.title:
            return chapter
        content = self.read_content_exact(chapter.id, connection=connection)
        content_hash = _hash(content)
        version_id = new_id()
        snapshot_relative = (
            Path(".ai_pipeline")
            / "history"
            / chapter.id
            / f"revision_{chapter.revision}_{version_id}.md"
        )
        snapshot = self.project.layout.root / snapshot_relative
        now = _now()
        current = connection.execute(
            "SELECT title, revision, content_hash FROM chapters WHERE id = ? AND is_deleted = 0",
            (chapter.id,),
        ).fetchone()
        if current is None:
            raise KeyError(f"unknown chapter: {chapter.id}")
        if (
            int(current["revision"]) != chapter.revision
            or str(current["title"]) != chapter.title
            or str(current["content_hash"]) != content_hash
        ):
            raise RuntimeError("chapter changed concurrently")
        file_transaction.register_created_file(snapshot)
        atomic_write_text(snapshot, content)
        connection.execute(
            "INSERT INTO chapter_versions VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                version_id,
                chapter.id,
                chapter.revision,
                snapshot_relative.as_posix(),
                _METADATA_CHANGE_SOURCE,
                _CHAPTER_TITLE_CHANGE_REASON,
                now.isoformat(),
                content_hash,
            ),
        )
        cursor = connection.execute(
            """
            UPDATE chapters
            SET title = ?, revision = revision + 1, memory_status = 'stale',
                updated_at = ?
            WHERE id = ? AND revision = ? AND title = ? AND content_hash = ?
              AND is_deleted = 0
            """,
            (
                normalized,
                now.isoformat(),
                chapter.id,
                chapter.revision,
                chapter.title,
                content_hash,
            ),
        )
        if cursor.rowcount != 1:
            raise RuntimeError("chapter changed concurrently")
        MemoryDependencyRepository.invalidate_formal_manuscript_in_connection(
            connection,
            chapter.id,
            chapter.revision + 1,
            content_hash,
        )
        MemoryDependencyRepository.invalidate_in_connection(
            connection,
            chapter.id,
            chapter.revision + 1,
            content_hash,
        )
        ViewAssertionRepository.invalidate_source_revision_in_connection(
            connection,
            source_id=chapter.id,
            new_revision=chapter.revision + 1,
            updated_at=now.isoformat(),
        )
        OccurrenceRepository.invalidate_source_revision_in_connection(
            connection,
            source_id=chapter.id,
            new_revision=chapter.revision + 1,
            updated_at=now.isoformat(),
        )
        if self.read_content_exact(chapter.id, connection=connection) != content:
            raise RuntimeError("chapter content changed during title update")
        return self.get_chapter(
            chapter.id,
            include_deleted=False,
            connection=connection,
        )

    def save_content(
        self,
        chapter_id: str,
        content: str,
        *,
        source: str,
        reason: str,
        invalidate_memory: bool = True,
        expected_revision: int | None = None,
        connection: sqlite3.Connection | None = None,
        file_transaction: ChapterFileTransaction | None = None,
    ) -> Chapter:
        if connection is None:
            if file_transaction is not None:
                raise ValueError("chapter file transaction requires a connection")
            owned = self.project.database.connect()
            local_files = ChapterFileTransaction()
            try:
                with owned:
                    chapter = self._save_content(
                        owned,
                        local_files,
                        chapter_id,
                        content,
                        source=source,
                        reason=reason,
                        invalidate_memory=invalidate_memory,
                        expected_revision=expected_revision,
                    )
            except BaseException:
                local_files.rollback()
                raise
            else:
                local_files.finalize()
                return chapter
            finally:
                owned.close()
        if file_transaction is None:
            raise ValueError("caller connection requires a chapter file transaction")
        return self._save_content(
            connection,
            file_transaction,
            chapter_id,
            content,
            source=source,
            reason=reason,
            invalidate_memory=invalidate_memory,
            expected_revision=expected_revision,
        )

    def _save_content(
        self,
        connection: sqlite3.Connection,
        file_transaction: ChapterFileTransaction,
        chapter_id: str,
        content: str,
        *,
        source: str,
        reason: str,
        invalidate_memory: bool,
        expected_revision: int | None,
    ) -> Chapter:
        chapter = self.get_chapter(
            chapter_id,
            include_deleted=False,
            connection=connection,
        )
        if expected_revision is not None and chapter.revision != expected_revision:
            raise StaleChapterRevisionError(
                "chapter revision changed: "
                f"expected {expected_revision}, current {chapter.revision}"
            )
        canonical = self._resolve_manuscript_path(chapter.content_path)
        previous = self._read_content_path_exact(chapter.content_path)
        version_id = new_id()
        snapshot_relative = (
            Path(".ai_pipeline")
            / "history"
            / chapter.id
            / f"revision_{chapter.revision}_{version_id}.md"
        )
        snapshot = self.project.layout.root / snapshot_relative
        file_transaction.register_created_file(snapshot)
        atomic_write_text(snapshot, previous)
        file_transaction.register_replaced_text(canonical, previous)
        atomic_write_text(canonical, content)
        now = _now()
        previous_hash = _hash(previous)
        content_hash = _hash(content)
        connection.execute(
            "INSERT INTO chapter_versions VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                version_id,
                chapter.id,
                chapter.revision,
                snapshot_relative.as_posix(),
                source,
                reason,
                now.isoformat(),
                previous_hash,
            ),
        )
        cursor = connection.execute(
            """
            UPDATE chapters SET revision = revision + 1, content_hash = ?,
            memory_status = CASE WHEN ? THEN 'stale' ELSE memory_status END,
            updated_at = ?
            WHERE id = ? AND revision = ? AND content_hash = ? AND is_deleted = 0
            """,
            (
                content_hash,
                int(invalidate_memory),
                now.isoformat(),
                chapter.id,
                chapter.revision,
                previous_hash,
            ),
        )
        if cursor.rowcount != 1:
            raise RuntimeError("chapter changed concurrently")
        MemoryDependencyRepository.invalidate_formal_manuscript_in_connection(
            connection,
            chapter.id,
            chapter.revision + 1,
            content_hash,
        )
        if invalidate_memory:
            MemoryDependencyRepository.invalidate_in_connection(
                connection,
                chapter.id,
                chapter.revision + 1,
                content_hash,
            )
            ViewAssertionRepository.invalidate_source_revision_in_connection(
                connection,
                source_id=chapter.id,
                new_revision=chapter.revision + 1,
                updated_at=now.isoformat(),
            )
            OccurrenceRepository.invalidate_source_revision_in_connection(
                connection,
                source_id=chapter.id,
                new_revision=chapter.revision + 1,
                updated_at=now.isoformat(),
            )
        return self.get_chapter(
            chapter.id,
            include_deleted=False,
            connection=connection,
        )

    def list_versions(self, chapter_id: str) -> list[ChapterVersion]:
        validate_id(chapter_id)
        connection = self.project.database.connect()
        try:
            rows = connection.execute(
                "SELECT * FROM chapter_versions WHERE chapter_id = ? ORDER BY revision",
                (chapter_id,),
            ).fetchall()
        finally:
            connection.close()
        return [
            ChapterVersion(
                row["id"],
                row["chapter_id"],
                row["revision"],
                row["content_snapshot_path"],
                row["source"],
                row["reason"],
                _parse_time(row["created_at"]),
                row["content_hash"],
            )
            for row in rows
        ]

    def delete_chapter(
        self,
        chapter_id: str,
        *,
        expected_revision: int | None = None,
        expected_source_hash: str | None = None,
    ) -> None:
        chapter = self.get_chapter(chapter_id, include_deleted=False)
        content_hash = _hash(self.read_content_exact(chapter.id))
        if expected_revision is not None and expected_revision != chapter.revision:
            raise RuntimeError("chapter changed before deletion")
        if expected_source_hash is not None and expected_source_hash != content_hash:
            raise RuntimeError("chapter changed before deletion")
        canonical = self.project.layout.root / chapter.content_path
        trash_relative = (
            Path(".ai_pipeline") / "trash" / f"chapter_{chapter.id}_r{chapter.revision}.md"
        )
        trash = self.project.layout.root / trash_relative
        trash.parent.mkdir(parents=True, exist_ok=True)
        connection = self.project.database.connect()
        source_moved = False
        try:
            connection.execute("BEGIN IMMEDIATE")
            current = connection.execute(
                """
                SELECT revision, content_hash, content_path FROM chapters
                WHERE id = ? AND is_deleted = 0
                """,
                (chapter.id,),
            ).fetchone()
            if (
                current is None
                or int(current["revision"]) != chapter.revision
                or str(current["content_hash"]) != content_hash
                or str(current["content_path"]) != chapter.content_path
            ):
                raise RuntimeError("chapter changed before deletion")
            os.replace(canonical, trash)
            source_moved = True
            cursor = connection.execute(
                """
                UPDATE chapters
                SET is_deleted = 1, deleted_content_path = ?, updated_at = ?
                WHERE id = ? AND revision = ? AND content_hash = ? AND is_deleted = 0
                """,
                (
                    trash_relative.as_posix(),
                    _now().isoformat(),
                    chapter.id,
                    chapter.revision,
                    content_hash,
                ),
            )
            if cursor.rowcount != 1:
                raise RuntimeError("chapter changed before deletion")
            invalidator = MemoryDependencyRepository
            invalidator.invalidate_formal_manuscript_for_deleted_chapter_in_connection(
                connection,
                chapter.id,
            )
            OccurrenceRepository.invalidate_for_deleted_chapter_in_connection(
                connection,
                source_id=chapter.id,
                updated_at=_now().isoformat(),
            )
            connection.commit()
        except BaseException:
            connection.rollback()
            if source_moved:
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
                "SELECT revision, content_hash, content_path, "
                "deleted_content_path FROM chapters WHERE id = ?",
                (chapter.id,),
            ).fetchone()
            if row is None or not row["deleted_content_path"]:
                raise RuntimeError("deleted chapter has no trash location")
            retained_revision = int(row["revision"])
            retained_hash = str(row["content_hash"])
            retained_content_path = str(row["content_path"])
            relative = Path(str(row["deleted_content_path"]))
            canonical = self._resolve_manuscript_path(retained_content_path)
            trash_root = (self.project.layout.root / ".ai_pipeline" / "trash").resolve()
            trash = (self.project.layout.root / relative).resolve()
            if not trash.is_relative_to(trash_root):
                raise RuntimeError("chapter restore source is invalid")
            if not trash.is_file():
                raise RuntimeError("chapter restore source is missing")
            try:
                with open(trash, encoding="utf-8", newline="") as handle:
                    restored_text = handle.read()
            except UnicodeDecodeError:
                raise RuntimeError("chapter restore source is invalid") from None
            verified_hash = hashlib.sha256(restored_text.encode("utf-8")).hexdigest()
            if verified_hash != retained_hash:
                raise RuntimeError("chapter restore source changed")

            connection.execute("BEGIN IMMEDIATE")
            moved = False
            try:
                current = connection.execute(
                    "SELECT is_deleted, revision, content_hash, "
                    "content_path, deleted_content_path "
                    "FROM chapters WHERE id = ?",
                    (chapter.id,),
                ).fetchone()
                identity_consistent = (
                    current is not None
                    and int(current["is_deleted"]) == 1
                    and int(current["revision"]) == retained_revision
                    and str(current["content_hash"]) == retained_hash
                    and str(current["content_path"]) == retained_content_path
                    and str(current["deleted_content_path"]) == relative.as_posix()
                )
                if not identity_consistent:
                    raise RuntimeError("chapter changed before restore")
                canonical.parent.mkdir(parents=True, exist_ok=True)
                os.replace(trash, canonical)
                moved = True
                try:
                    with open(canonical, encoding="utf-8", newline="") as handle:
                        moved_text = handle.read()
                except UnicodeDecodeError:
                    raise RuntimeError("chapter restore source is invalid") from None
                moved_hash = hashlib.sha256(moved_text.encode("utf-8")).hexdigest()
                if moved_hash != retained_hash:
                    raise RuntimeError("chapter restore source changed")
                cursor = connection.execute(
                    "UPDATE chapters SET is_deleted = 0, "
                    "deleted_content_path = NULL, updated_at = ? "
                    "WHERE id = ? AND is_deleted = 1 AND revision = ? "
                    "AND content_hash = ? AND content_path = ? "
                    "AND deleted_content_path = ?",
                    (
                        _now().isoformat(),
                        chapter.id,
                        retained_revision,
                        retained_hash,
                        retained_content_path,
                        relative.as_posix(),
                    ),
                )
                if cursor.rowcount != 1:
                    raise RuntimeError("chapter changed before restore")
                connection.commit()
            except BaseException:
                connection.rollback()
                if moved:
                    os.replace(canonical, trash)
                raise
        finally:
            connection.close()
        return self.get_chapter(chapter.id)

    def delete_volume(
        self,
        volume_id: str,
        target_volume_id: str,
        *,
        expected_sources: tuple[ChapterRelocationExpectation, ...] | None = None,
    ) -> tuple[Chapter, ...]:
        validate_id(volume_id)
        validate_id(target_volume_id)
        if volume_id == target_volume_id:
            raise ValueError("target volume must be different from deleted volume")
        if expected_sources is not None and (
            not isinstance(expected_sources, tuple)
            or any(
                not isinstance(source, ChapterRelocationExpectation) for source in expected_sources
            )
        ):
            raise TypeError("chapter relocation expectations are invalid")
        moved_paths: list[tuple[Path, Path]] = []
        snapshots: list[Path] = []
        connection = self.project.database.connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            target_exists = connection.execute(
                "SELECT 1 FROM volumes WHERE id = ?", (target_volume_id,)
            ).fetchone()
            source_exists = connection.execute(
                "SELECT 1 FROM volumes WHERE id = ?", (volume_id,)
            ).fetchone()
            if target_exists is None or source_exists is None:
                raise KeyError("source or target volume does not exist")
            deleted_exists = connection.execute(
                "SELECT 1 FROM chapters WHERE volume_id = ? AND is_deleted = 1 LIMIT 1",
                (volume_id,),
            ).fetchone()
            if deleted_exists is not None:
                raise RuntimeError("source volume contains deleted chapters")
            moving_rows = connection.execute(
                "SELECT * FROM chapters WHERE volume_id = ? AND is_deleted = 0 "
                "ORDER BY sort_index, id",
                (volume_id,),
            ).fetchall()
            moving = tuple(_chapter_from_row(row) for row in moving_rows)
            actual_sources = tuple(
                ChapterRelocationExpectation(
                    chapter.id,
                    chapter.revision,
                    str(row["content_hash"]),
                )
                for chapter, row in zip(moving, moving_rows, strict=True)
            )
            if expected_sources is not None and expected_sources != actual_sources:
                raise RuntimeError("source volume chapters changed before deletion")
            prepared: list[tuple[Chapter, str, Path, Path, Path]] = []
            for chapter, row in zip(moving, moving_rows, strict=True):
                content = self._read_content_path_exact(chapter.content_path)
                if _hash(content) != str(row["content_hash"]):
                    raise RuntimeError("chapter content does not match its stored hash")
                new_relative = (
                    Path("manuscript") / f"volume_{target_volume_id}" / f"chapter_{chapter.id}.md"
                )
                old_path = self._resolve_manuscript_path(chapter.content_path)
                new_path = self._resolve_manuscript_path(new_relative)
                if new_path.exists() or new_path.is_symlink():
                    raise RuntimeError("target chapter path already exists")
                prepared.append((chapter, content, old_path, new_path, new_relative))
            next_index = int(
                connection.execute(
                    "SELECT COALESCE(MAX(sort_index), -1) + 1 FROM chapters "
                    "WHERE volume_id = ? AND is_deleted = 0",
                    (target_volume_id,),
                ).fetchone()[0]
            )
            now = _now()
            for offset, (chapter, content, old_path, new_path, new_relative) in enumerate(prepared):
                content_hash = _hash(content)
                version_id = new_id()
                snapshot_relative = (
                    Path(".ai_pipeline")
                    / "history"
                    / chapter.id
                    / f"revision_{chapter.revision}_{version_id}.md"
                )
                snapshot = self.project.layout.root / snapshot_relative
                atomic_write_text(snapshot, content)
                snapshots.append(snapshot)
                connection.execute(
                    "INSERT INTO chapter_versions VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        version_id,
                        chapter.id,
                        chapter.revision,
                        snapshot_relative.as_posix(),
                        _METADATA_CHANGE_SOURCE,
                        _CHAPTER_RELOCATION_REASON,
                        now.isoformat(),
                        content_hash,
                    ),
                )
                new_path.parent.mkdir(parents=True, exist_ok=True)
                os.replace(old_path, new_path)
                moved_paths.append((old_path, new_path))
                cursor = connection.execute(
                    """
                    UPDATE chapters
                    SET volume_id = ?, content_path = ?, sort_index = ?,
                        revision = revision + 1, memory_status = 'stale', updated_at = ?
                    WHERE id = ? AND volume_id = ? AND content_path = ?
                      AND revision = ? AND content_hash = ? AND is_deleted = 0
                    """,
                    (
                        target_volume_id,
                        new_relative.as_posix(),
                        next_index + offset,
                        now.isoformat(),
                        chapter.id,
                        volume_id,
                        chapter.content_path,
                        chapter.revision,
                        content_hash,
                    ),
                )
                if cursor.rowcount != 1:
                    raise RuntimeError("chapter changed during volume deletion")
                MemoryDependencyRepository.invalidate_formal_manuscript_in_connection(
                    connection,
                    chapter.id,
                    chapter.revision + 1,
                    content_hash,
                )
                MemoryDependencyRepository.invalidate_in_connection(
                    connection,
                    chapter.id,
                    chapter.revision + 1,
                    content_hash,
                )
                ViewAssertionRepository.invalidate_source_revision_in_connection(
                    connection,
                    source_id=chapter.id,
                    new_revision=chapter.revision + 1,
                    updated_at=now.isoformat(),
                )
                OccurrenceRepository.invalidate_source_revision_in_connection(
                    connection,
                    source_id=chapter.id,
                    new_revision=chapter.revision + 1,
                    updated_at=now.isoformat(),
                )
                connection.execute(
                    "UPDATE memory_documents SET volume_id = ? WHERE chapter_id = ?",
                    (target_volume_id, chapter.id),
                )
                if self._read_content_path_exact(new_relative.as_posix()) != content:
                    raise RuntimeError("chapter content changed during volume deletion")
            cursor = connection.execute("DELETE FROM volumes WHERE id = ?", (volume_id,))
            if cursor.rowcount != 1:
                raise RuntimeError("source volume changed during deletion")
            connection.commit()
        except BaseException:
            connection.rollback()
            for old_path, new_path in reversed(moved_paths):
                old_path.parent.mkdir(parents=True, exist_ok=True)
                if new_path.exists():
                    os.replace(new_path, old_path)
            for snapshot in snapshots:
                snapshot.unlink(missing_ok=True)
            raise
        finally:
            connection.close()
        return tuple(self.get_chapter(chapter.id, include_deleted=False) for chapter in moving)
