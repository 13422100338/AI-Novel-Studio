from __future__ import annotations

import os
import sqlite3
from contextlib import closing
from datetime import UTC, datetime, timedelta
from pathlib import Path

from ai_novel_studio.domain.identifiers import new_id, validate_id
from ai_novel_studio.domain.outline import (
    MAX_OUTLINE_BYTES,
    OutlineDocument,
    OutlineSnapshot,
    OutlineVersion,
    outline_content_hash,
    validate_outline_hash,
)
from ai_novel_studio.infrastructure.storage.atomic_file import atomic_write_text
from ai_novel_studio.infrastructure.storage.project_repository import ProjectRepository


class OutlineConflictError(RuntimeError):
    pass


class OutlineIntegrityError(RuntimeError):
    pass


def read_outline_text(path: Path) -> str:
    """Read UTF-8 verbatim, including BOM and CRLF; never normalize or truncate."""
    with path.open("rb") as stream:
        payload = stream.read(MAX_OUTLINE_BYTES + 1)
    if len(payload) > MAX_OUTLINE_BYTES:
        raise ValueError("大纲超过 20 MB 存储上限，未读取或截断")
    content = payload.decode("utf-8")
    outline_content_hash(content)
    return content


class OutlineRepository:
    """Versioned Markdown assets, independent of chapter and memory mutations."""

    def __init__(self, project: ProjectRepository) -> None:
        self.project = project

    def list_documents(self) -> tuple[OutlineDocument, ...]:
        with closing(self.project.database.connect()) as connection:
            rows = connection.execute(
                "SELECT * FROM outline_documents WHERE project_id = ? ORDER BY sort_index, id",
                (self.project.project.id,),
            ).fetchall()
        return tuple(self._document(row) for row in rows)

    def get(self, document_id: str) -> OutlineDocument:
        with closing(self.project.database.connect()) as connection:
            return self._get(connection, document_id)

    def read_bundle(self) -> tuple[tuple[OutlineDocument, OutlineSnapshot], ...]:
        """Freeze every registered outline in one read transaction, without model selection."""
        with closing(self.project.database.connect()) as connection, connection:
            connection.execute("BEGIN")
            rows = connection.execute(
                "SELECT * FROM outline_documents WHERE project_id=? ORDER BY sort_index, id",
                (self.project.project.id,),
            ).fetchall()
            result = []
            for row in rows:
                document = self._document(row)
                snapshot = self._registered_snapshot(connection, document)
                self._verify_working(document.id, snapshot.content)
                result.append((document, snapshot))
            return tuple(result)

    def reorder(self, document_ids: tuple[str, ...], *, expected_order: tuple[str, ...]) -> None:
        with closing(self.project.database.connect()) as connection, connection:
            connection.execute("BEGIN IMMEDIATE")
            rows = connection.execute(
                "SELECT id, updated_at FROM outline_documents "
                "WHERE project_id = ? ORDER BY sort_index, id",
                (self.project.project.id,),
            ).fetchall()
            current = tuple(row["id"] for row in rows)
            if current != expected_order:
                raise OutlineConflictError("大纲文档顺序已变更，请刷新后重试")
            if len(document_ids) != len(current) or set(document_ids) != set(current):
                raise ValueError("排序必须包含当前项目的全部大纲文档，且不能重复")
            if document_ids == current:
                return
            # Preserve a distinct metadata version even if order or the system clock goes back.
            updated_at = max(
                datetime.now(UTC),
                max(datetime.fromisoformat(row["updated_at"]) for row in rows)
                + timedelta(microseconds=1),
            ).isoformat()
            connection.executemany(
                "UPDATE outline_documents SET sort_index = ?, updated_at = ? "
                "WHERE id = ? AND project_id = ?",
                [
                    (index, updated_at, item, self.project.project.id)
                    for index, item in enumerate(document_ids)
                ],
            )

    def create(self, title: str, content: str = "") -> OutlineSnapshot:
        digest = outline_content_hash(content)
        now = datetime.now(UTC)
        with closing(self.project.database.connect()) as connection, connection:
            connection.execute("BEGIN IMMEDIATE")
            position = connection.execute(
                "SELECT COALESCE(MAX(sort_index), -1) + 1 FROM outline_documents "
                "WHERE project_id = ?",
                (self.project.project.id,),
            ).fetchone()[0]
            document = OutlineDocument(
                new_id(), self.project.project.id, title, position, 1, digest, now, now
            )
            version = OutlineVersion(new_id(), document.id, 1, digest, now)
            self._write_snapshot(version, content)
            self._publish_new_file(self._working_path(document.id), content)
            self._verify_working(document.id, content)
            connection.execute(
                "INSERT INTO outline_documents VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    document.id,
                    document.project_id,
                    title,
                    position,
                    1,
                    digest,
                    now.isoformat(),
                    now.isoformat(),
                ),
            )
            self._insert_version(connection, version)
        return OutlineSnapshot(version, content)

    def read(self, document_id: str) -> OutlineSnapshot:
        with closing(self.project.database.connect()) as connection, connection:
            connection.execute("BEGIN")
            document = self._get(connection, document_id)
            snapshot = self._registered_snapshot(connection, document)
            self._verify_working(document.id, snapshot.content)
            return snapshot

    def read_version(self, document_id: str, revision: int) -> OutlineSnapshot:
        self._validate_revision(revision)
        with closing(self.project.database.connect()) as connection:
            self._get(connection, document_id)
            return self._read_version(connection, document_id, revision)

    def list_versions(self, document_id: str) -> tuple[OutlineVersion, ...]:
        with closing(self.project.database.connect()) as connection:
            self._get(connection, document_id)
            rows = connection.execute(
                "SELECT * FROM outline_versions WHERE document_id = ? ORDER BY revision",
                (document_id,),
            ).fetchall()
        return tuple(self._version(row) for row in rows)

    def save(self, document_id: str, content: str, *, expected_revision: int) -> OutlineSnapshot:
        return self._save(document_id, content, expected_revision=expected_revision)

    def inspect_working_copy(self, document_id: str) -> str:
        """Unregistered disk content for author review only, never model input."""
        self.get(document_id)
        return self._working_text(document_id)

    def recover_from_disk(
        self, document_id: str, *, expected_revision: int, expected_disk_hash: str
    ) -> OutlineSnapshot:
        """Explicitly register the author's reviewed disk copy as a new version."""
        validate_outline_hash(expected_disk_hash)
        content = self.inspect_working_copy(document_id)
        if outline_content_hash(content) != expected_disk_hash:
            raise OutlineConflictError("磁盘大纲已再次变更，请重新检查后恢复")
        return self._save(
            document_id,
            content,
            expected_revision=expected_revision,
            expected_disk_hash=expected_disk_hash,
        )

    def restore_missing_working_copy(
        self, document_id: str, *, expected_revision: int
    ) -> OutlineSnapshot:
        """Explicitly recreate a missing working file from the committed snapshot."""
        self._validate_revision(expected_revision)
        with closing(self.project.database.connect()) as connection, connection:
            connection.execute("BEGIN IMMEDIATE")
            document = self._get(connection, document_id)
            if document.revision != expected_revision:
                raise OutlineConflictError("大纲版本已变更，请重新检查后恢复")
            snapshot = self._registered_snapshot(connection, document)
            try:
                self._publish_new_file(self._working_path(document.id), snapshot.content)
            except FileExistsError as exc:
                raise OutlineConflictError("磁盘大纲已存在，请检查后选择恢复方式") from exc
            self._verify_working(document.id, snapshot.content)
            return snapshot

    def _save(
        self,
        document_id: str,
        content: str,
        *,
        expected_revision: int,
        expected_disk_hash: str | None = None,
    ) -> OutlineSnapshot:
        digest = outline_content_hash(content)
        self._validate_revision(expected_revision)
        with closing(self.project.database.connect()) as connection, connection:
            connection.execute("BEGIN IMMEDIATE")
            document = self._get(connection, document_id)
            if document.revision != expected_revision:
                raise OutlineConflictError("大纲版本已变更，请重新打开后再保存")
            current = self._registered_snapshot(connection, document)
            expected = expected_disk_hash or document.content_hash
            if outline_content_hash(self._working_text(document.id)) != expected:
                raise OutlineConflictError("磁盘大纲与登记版本不一致，请检查并显式恢复")
            if digest == document.content_hash:
                return current
            version = OutlineVersion(
                new_id(), document.id, document.revision + 1, digest, datetime.now(UTC)
            )
            self._write_snapshot(version, content)
            if expected != digest:
                self._replace_working(document.id, content, expected)
            self._verify_working(document.id, content)
            self._insert_version(connection, version)
            cursor = connection.execute(
                "UPDATE outline_documents SET revision = ?, content_hash = ?, updated_at = ? "
                "WHERE id = ? AND project_id = ? AND revision = ? AND content_hash = ?",
                (
                    version.revision,
                    digest,
                    version.created_at.isoformat(),
                    document.id,
                    document.project_id,
                    document.revision,
                    document.content_hash,
                ),
            )
            if cursor.rowcount != 1:
                raise OutlineConflictError("大纲版本已变更，请重新检查")
            # Files are retained on SQL/commit failure. read() then fails closed;
            # the author can inspect and explicitly recover_from_disk, without data loss.
            return OutlineSnapshot(version, content)

    def _get(self, connection: sqlite3.Connection, document_id: str) -> OutlineDocument:
        validate_id(document_id)
        row = connection.execute(
            "SELECT * FROM outline_documents WHERE id = ? AND project_id = ?",
            (document_id, self.project.project.id),
        ).fetchone()
        if row is None:
            raise KeyError("找不到当前项目的大纲")
        return self._document(row)

    def _registered_snapshot(
        self, connection: sqlite3.Connection, document: OutlineDocument
    ) -> OutlineSnapshot:
        try:
            snapshot = self._read_version(connection, document.id, document.revision)
        except KeyError as exc:
            raise OutlineIntegrityError("当前大纲版本快照缺失") from exc
        if snapshot.version.content_hash != document.content_hash:
            raise OutlineIntegrityError("大纲登记哈希与版本不一致")
        return snapshot

    def _read_version(
        self, connection: sqlite3.Connection, document_id: str, revision: int
    ) -> OutlineSnapshot:
        row = connection.execute(
            "SELECT * FROM outline_versions WHERE document_id = ? AND revision = ?",
            (document_id, revision),
        ).fetchone()
        if row is None:
            raise KeyError("找不到大纲版本")
        version = self._version(row)
        content = self._read_asset(self._snapshot_path(version))
        if outline_content_hash(content) != version.content_hash:
            raise OutlineIntegrityError("大纲版本文件已损坏或被修改")
        return OutlineSnapshot(version, content)

    def _working_path(self, document_id: str) -> Path:
        validate_id(document_id)
        return self._checked_path(self.project.layout.root / "outlines" / f"{document_id}.md")

    def _snapshot_path(self, version: OutlineVersion) -> Path:
        return self._checked_path(
            self.project.layout.pipeline
            / "outline_versions"
            / version.document_id
            / f"{version.id}.md"
        )

    @staticmethod
    def _checked_path(path: Path) -> Path:
        if path.resolve() != path:
            raise OutlineIntegrityError("大纲路径被重定向，拒绝读写")
        return path

    def _write_snapshot(self, version: OutlineVersion, content: str) -> None:
        path = self._snapshot_path(version)
        path.parent.mkdir(parents=True, exist_ok=True)
        self._checked_path(path)
        # Unpublished snapshots are immutable and only become visible after SQL commit.
        with path.open("x", encoding="utf-8", newline="") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())

    def _publish_new_file(self, path: Path, content: str) -> None:
        """Publish a complete, independent file without replacing any existing path."""
        self._checked_path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        staging = self._checked_path(path.with_name(f".outline-{new_id()}.pending"))
        with staging.open("x", encoding="utf-8", newline=""):
            pass
        try:
            atomic_write_text(staging, content)
            self._checked_path(path)
            # Hard-link only this private staging file, never a retained snapshot/copy.
            os.link(staging, path)
        finally:
            staging.unlink(missing_ok=True)

    def _replace_working(self, document_id: str, content: str, expected_hash: str) -> None:
        working = self._working_path(document_id)
        retained = self._checked_path(
            self.project.layout.pipeline / "outline_versions" / document_id / f"disk_{new_id()}.md"
        )
        if retained.exists():
            raise FileExistsError("磁盘恢复副本已存在")
        # Moving, rather than reading then replacing, retains the actual displaced file.
        os.rename(working, retained)
        try:
            displaced = self._read_asset(retained)
            if outline_content_hash(displaced) != expected_hash:
                raise OutlineConflictError("保存边界出现外部修改，已保留磁盘副本")
            self._publish_new_file(working, content)
        except BaseException as exc:
            try:
                self._publish_new_file(working, self._read_asset(retained))
            except (OSError, ValueError, OutlineIntegrityError):
                # Keep all recovery assets if the disk is full or another writer won.
                pass
            if isinstance(exc, FileExistsError):
                raise OutlineConflictError("保存期间大纲被其他操作重建，已保留磁盘副本") from exc
            raise

    def _working_text(self, document_id: str) -> str:
        return self._read_asset(self._working_path(document_id))

    def _verify_working(self, document_id: str, content: str) -> None:
        if self._working_text(document_id) != content:
            raise OutlineIntegrityError("磁盘大纲与登记版本不一致，请检查并显式恢复")

    @staticmethod
    def _read_asset(path: Path) -> str:
        try:
            return read_outline_text(path)
        except (OSError, ValueError) as exc:
            raise OutlineIntegrityError("大纲文件缺失、损坏或无法读取") from exc

    @staticmethod
    def _validate_revision(revision: int) -> None:
        if type(revision) is not int or revision < 1:
            raise ValueError("大纲修订号无效")

    @staticmethod
    def _insert_version(connection: sqlite3.Connection, version: OutlineVersion) -> None:
        connection.execute(
            "INSERT INTO outline_versions VALUES (?, ?, ?, ?, ?)",
            (
                version.id,
                version.document_id,
                version.revision,
                version.content_hash,
                version.created_at.isoformat(),
            ),
        )

    @staticmethod
    def _document(row: sqlite3.Row) -> OutlineDocument:
        return OutlineDocument(
            row["id"],
            row["project_id"],
            row["title"],
            row["sort_index"],
            row["revision"],
            row["content_hash"],
            datetime.fromisoformat(row["created_at"]),
            datetime.fromisoformat(row["updated_at"]),
        )

    @staticmethod
    def _version(row: sqlite3.Row) -> OutlineVersion:
        return OutlineVersion(
            row["id"],
            row["document_id"],
            row["revision"],
            row["content_hash"],
            datetime.fromisoformat(row["created_at"]),
        )
