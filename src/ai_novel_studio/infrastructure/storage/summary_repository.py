from __future__ import annotations

import hashlib
import json
import sqlite3
from datetime import UTC, datetime

from ai_novel_studio.domain.identifiers import new_id
from ai_novel_studio.domain.memory import (
    Authority,
    MemoryStatus,
    ReviewStatus,
    SourceType,
    SummaryLevel,
    SummaryNode,
)
from ai_novel_studio.infrastructure.storage.narrative_memory_repository import (
    ProtectedMemoryError,
)
from ai_novel_studio.infrastructure.storage.project_repository import ProjectRepository


def _now() -> datetime:
    return datetime.now(UTC)


def _hash(content: str) -> str:
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


class StaleSummaryWriteError(RuntimeError):
    pass


class SummaryRepository:
    def __init__(self, project: ProjectRepository) -> None:
        self.project = project

    def add_candidate(
        self,
        level: SummaryLevel,
        scope_id: str,
        content: str,
        source_chapter_ids: tuple[str, ...],
        *,
        model_profile_id: str,
    ) -> SummaryNode:
        return self._add(
            level,
            scope_id,
            content,
            source_chapter_ids,
            model_profile_id=model_profile_id,
            authority=Authority.MODEL_EXTRACTED,
            review_status=ReviewStatus.REVIEW,
            status=MemoryStatus.REVIEW,
        )

    def add_human_summary(
        self,
        level: SummaryLevel,
        scope_id: str,
        content: str,
        source_chapter_ids: tuple[str, ...],
        *,
        authority: Authority,
        review_status: ReviewStatus,
    ) -> SummaryNode:
        return self._add(
            level,
            scope_id,
            content,
            source_chapter_ids,
            model_profile_id=None,
            authority=authority,
            review_status=review_status,
            status=MemoryStatus.CURRENT,
        )

    def _add(
        self,
        level: SummaryLevel,
        scope_id: str,
        content: str,
        source_chapter_ids: tuple[str, ...],
        *,
        model_profile_id: str | None,
        authority: Authority,
        review_status: ReviewStatus,
        status: MemoryStatus,
    ) -> SummaryNode:
        if not scope_id.strip() or not content.strip() or not source_chapter_ids:
            raise ValueError("摘要范围、内容和来源章节不能为空")
        revisions = self._source_revisions(source_chapter_ids)
        summary = SummaryNode(
            new_id(),
            level,
            scope_id,
            content.strip(),
            source_chapter_ids,
            revisions,
            _hash(content.strip()),
            model_profile_id,
            authority,
            review_status,
            status,
            0,
            _now(),
        )
        now = summary.created_at.isoformat()
        with self.project.database.connect() as connection, connection:
            connection.execute(
                "INSERT INTO summary_nodes VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    summary.id,
                    summary.level.value,
                    summary.scope_id,
                    summary.content,
                    json.dumps(summary.source_chapter_ids),
                    json.dumps(summary.source_revisions),
                    summary.content_hash,
                    summary.model_profile_id,
                    summary.authority.value,
                    summary.review_status.value,
                    summary.status.value,
                    summary.revision,
                    now,
                    now,
                ),
            )
            for chapter_id, revision, content_hash in summary.source_revisions:
                connection.execute(
                    "INSERT INTO memory_dependencies VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (
                        new_id(),
                        "SUMMARY",
                        summary.id,
                        chapter_id,
                        revision,
                        content_hash,
                        MemoryStatus.CURRENT.value,
                    ),
                )
        return summary

    def get(self, summary_id: str) -> SummaryNode:
        with self.project.database.connect() as connection:
            row = connection.execute(
                "SELECT * FROM summary_nodes WHERE id = ?", (summary_id,)
            ).fetchone()
        if row is None:
            raise KeyError(f"unknown summary: {summary_id}")
        return self._summary(row)

    def list_scope(self, level: SummaryLevel, scope_id: str) -> tuple[SummaryNode, ...]:
        with self.project.database.connect() as connection:
            rows = connection.execute(
                """
                SELECT * FROM summary_nodes WHERE level = ? AND scope_id = ?
                ORDER BY revision DESC, created_at DESC, id
                """,
                (level.value, scope_id),
            ).fetchall()
        return tuple(self._summary(row) for row in rows)

    def promote(self, summary_id: str, *, expected_revision: int) -> SummaryNode:
        summary = self.get(summary_id)
        if summary.review_status == ReviewStatus.LOCKED:
            raise ProtectedMemoryError("锁定摘要不能重复晋升")
        now = _now().isoformat()
        with self.project.database.connect() as connection, connection:
            cursor = connection.execute(
                """
                UPDATE summary_nodes
                SET review_status = 'APPROVED', status = 'CURRENT',
                    revision = revision + 1, updated_at = ?
                WHERE id = ? AND revision = ?
                """,
                (now, summary_id, expected_revision),
            )
            if cursor.rowcount != 1:
                raise StaleSummaryWriteError("摘要修订已变化，请重新审查")
        return self.get(summary_id)

    def update_content(
        self,
        summary_id: str,
        content: str,
        source_type: SourceType,
        *,
        expected_revision: int,
    ) -> SummaryNode:
        summary = self.get(summary_id)
        if summary.review_status == ReviewStatus.LOCKED:
            raise ProtectedMemoryError("锁定摘要不可修改")
        if source_type == SourceType.MODEL and summary.authority == Authority.USER_CONFIRMED:
            raise ProtectedMemoryError("模型不能覆盖用户确认摘要")
        if not content.strip():
            raise ValueError("摘要内容不能为空")
        with self.project.database.connect() as connection, connection:
            cursor = connection.execute(
                """
                UPDATE summary_nodes SET content = ?, content_hash = ?,
                    revision = revision + 1, updated_at = ?
                WHERE id = ? AND revision = ?
                """,
                (
                    content.strip(),
                    _hash(content.strip()),
                    _now().isoformat(),
                    summary_id,
                    expected_revision,
                ),
            )
            if cursor.rowcount != 1:
                raise StaleSummaryWriteError("摘要修订已变化，请重新载入")
        return self.get(summary_id)

    def is_before(self, summary: SummaryNode, chapter_id: str) -> bool:
        placeholders = ",".join("?" for _ in summary.source_chapter_ids)
        with self.project.database.connect() as connection:
            row = connection.execute(
                f"""
                WITH target AS (
                    SELECT v.sort_index AS volume_order, c.sort_index AS chapter_order
                    FROM chapters c JOIN volumes v ON v.id = c.volume_id WHERE c.id = ?
                )
                SELECT COUNT(*) FROM chapters c JOIN volumes v ON v.id = c.volume_id
                CROSS JOIN target t
                WHERE c.id IN ({placeholders})
                  AND (v.sort_index < t.volume_order OR
                       (v.sort_index = t.volume_order AND c.sort_index < t.chapter_order))
                """,
                (chapter_id, *summary.source_chapter_ids),
            ).fetchone()
        return int(row[0]) == len(summary.source_chapter_ids)

    def _source_revisions(
        self, chapter_ids: tuple[str, ...]
    ) -> tuple[tuple[str, int, str], ...]:
        placeholders = ",".join("?" for _ in chapter_ids)
        with self.project.database.connect() as connection:
            rows = connection.execute(
                f"SELECT id, revision, content_hash FROM chapters WHERE id IN ({placeholders})",
                chapter_ids,
            ).fetchall()
        values = {row["id"]: (int(row["revision"]), row["content_hash"]) for row in rows}
        if len(values) != len(chapter_ids):
            raise KeyError("摘要引用了不存在的章节")
        return tuple((chapter_id, *values[chapter_id]) for chapter_id in chapter_ids)

    @staticmethod
    def _summary(row: sqlite3.Row) -> SummaryNode:
        source_ids = tuple(str(value) for value in json.loads(row["source_chapter_ids_json"]))
        source_revisions = tuple(
            (str(value[0]), int(value[1]), str(value[2]))
            for value in json.loads(row["source_revisions_json"])
        )
        return SummaryNode(
            row["id"],
            SummaryLevel(row["level"]),
            row["scope_id"],
            row["content"],
            source_ids,
            source_revisions,
            row["content_hash"],
            row["model_profile_id"],
            Authority(row["authority"]),
            ReviewStatus(row["review_status"]),
            MemoryStatus(row["status"]),
            int(row["revision"]),
            datetime.fromisoformat(row["created_at"]),
        )

