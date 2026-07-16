from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime

from ai_novel_studio.domain.identifiers import new_id
from ai_novel_studio.domain.memory import (
    Authority,
    CanonCategory,
    CanonEntry,
    ClueAction,
    ClueType,
    MemoryStatus,
    NarrativeClue,
    NarrativeClueEvent,
    ReviewStatus,
    SourceType,
)
from ai_novel_studio.infrastructure.storage.project_repository import ProjectRepository


def _now() -> datetime:
    return datetime.now(UTC)


def _time(value: str) -> datetime:
    return datetime.fromisoformat(value)


class ProtectedMemoryError(PermissionError):
    pass


@dataclass(frozen=True, slots=True)
class ClueTimeline:
    clue: NarrativeClue
    events: tuple[NarrativeClueEvent, ...]


class NarrativeMemoryRepository:
    def __init__(self, project: ProjectRepository) -> None:
        self.project = project

    def add_canon(
        self,
        title: str,
        detail: str,
        source_chapter_id: str | None,
        *,
        source_paragraph_id: str | None = None,
        confidence: float,
        authority: Authority,
        review_status: ReviewStatus,
        category: CanonCategory | None = None,
    ) -> CanonEntry:
        if not title.strip() or not detail.strip():
            raise ValueError("正典标题和详情不能为空")
        entry = CanonEntry(
            new_id(),
            title.strip(),
            detail.strip(),
            source_chapter_id,
            source_paragraph_id,
            confidence,
            authority,
            MemoryStatus.CURRENT,
            review_status,
            _now(),
            category,
        )
        with self.project.database.connect() as connection, connection:
            connection.execute(
                "INSERT INTO canon_entries "
                "(id, title, detail, source_chapter_id, source_paragraph_id, confidence, "
                "authority, status, review_status, created_at, updated_at, category) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    entry.id,
                    entry.title,
                    entry.detail,
                    entry.source_chapter_id,
                    entry.source_paragraph_id,
                    entry.confidence,
                    entry.authority.value,
                    entry.status.value,
                    entry.review_status.value,
                    entry.created_at.isoformat(),
                    entry.created_at.isoformat(),
                    entry.category.value if entry.category is not None else None,
                ),
            )
        return entry

    def canon_before(self, title: str, chapter_id: str) -> tuple[CanonEntry, ...]:
        with self.project.database.connect() as connection:
            rows = connection.execute(
                """
                WITH target AS (
                    SELECT v.sort_index AS volume_order, c.sort_index AS chapter_order
                    FROM chapters c JOIN volumes v ON v.id = c.volume_id WHERE c.id = ?
                )
                SELECT e.* FROM canon_entries e
                LEFT JOIN chapters c ON c.id = e.source_chapter_id
                LEFT JOIN volumes v ON v.id = c.volume_id
                CROSS JOIN target t
                WHERE e.title = ? AND e.status = 'CURRENT'
                  AND e.review_status IN ('APPROVED', 'LOCKED')
                  AND (e.source_chapter_id IS NULL OR v.sort_index < t.volume_order OR
                       (v.sort_index = t.volume_order AND c.sort_index < t.chapter_order))
                ORDER BY e.created_at, e.id
                """,
                (chapter_id, title),
            ).fetchall()
        return tuple(self._canon(row) for row in rows)

    def list_canon_before(self, chapter_id: str) -> tuple[CanonEntry, ...]:
        """Return all reviewed current canon facts visible before a chapter."""
        with self.project.database.connect() as connection:
            target = connection.execute(
                "SELECT 1 FROM chapters WHERE id = ? AND is_deleted = 0",
                (chapter_id,),
            ).fetchone()
            if target is None:
                raise KeyError(f"unknown chapter: {chapter_id}")
            rows = connection.execute(
                """
                WITH target AS (
                    SELECT v.sort_index AS volume_order, c.sort_index AS chapter_order
                    FROM chapters c JOIN volumes v ON v.id = c.volume_id
                    WHERE c.id = ? AND c.is_deleted = 0
                )
                SELECT e.* FROM canon_entries e
                LEFT JOIN chapters c ON c.id = e.source_chapter_id
                LEFT JOIN volumes v ON v.id = c.volume_id
                CROSS JOIN target t
                WHERE e.status = 'CURRENT'
                  AND e.review_status IN ('APPROVED', 'LOCKED')
                  AND (
                    e.source_chapter_id IS NULL OR
                    (
                      c.is_deleted = 0 AND
                      (
                        v.sort_index < t.volume_order OR
                        (v.sort_index = t.volume_order AND c.sort_index < t.chapter_order)
                      )
                    )
                  )
                ORDER BY
                  CASE WHEN e.source_chapter_id IS NULL THEN 0 ELSE 1 END,
                  COALESCE(v.sort_index, -1),
                  COALESCE(c.sort_index, -1),
                  e.created_at,
                  e.id
                """,
                (chapter_id,),
            ).fetchall()
        return tuple(self._canon(row) for row in rows)

    def add_clue(
        self,
        clue_type: ClueType,
        title: str,
        detail: str,
        authority: Authority,
        review_status: ReviewStatus,
    ) -> NarrativeClue:
        if not title.strip() or not detail.strip():
            raise ValueError("叙事线索标题和详情不能为空")
        clue = NarrativeClue(
            new_id(),
            clue_type,
            title.strip(),
            detail.strip(),
            authority,
            MemoryStatus.CURRENT,
            review_status,
            _now(),
        )
        with self.project.database.connect() as connection, connection:
            connection.execute(
                "INSERT INTO narrative_clues VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    clue.id,
                    clue.clue_type.value,
                    clue.title,
                    clue.detail,
                    clue.authority.value,
                    clue.status.value,
                    clue.review_status.value,
                    clue.created_at.isoformat(),
                    clue.created_at.isoformat(),
                ),
            )
        return clue

    def get_clue(self, clue_id: str) -> NarrativeClue:
        with self.project.database.connect() as connection:
            row = connection.execute(
                "SELECT * FROM narrative_clues WHERE id = ?", (clue_id,)
            ).fetchone()
        if row is None:
            raise KeyError(f"unknown narrative clue: {clue_id}")
        return self._clue(row)

    def append_clue_action(
        self,
        clue_id: str,
        chapter_id: str,
        action: ClueAction,
        detail: str,
        source_type: SourceType,
        review_status: ReviewStatus,
    ) -> NarrativeClueEvent:
        self.get_clue(clue_id)
        event = NarrativeClueEvent(
            new_id(),
            clue_id,
            chapter_id,
            action,
            detail,
            source_type,
            review_status,
            _now(),
        )
        with self.project.database.connect() as connection, connection:
            connection.execute(
                "INSERT INTO narrative_clue_events VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    event.id,
                    event.clue_id,
                    event.chapter_id,
                    event.action.value,
                    event.detail,
                    event.source_type.value,
                    event.review_status.value,
                    event.created_at.isoformat(),
                ),
            )
        return event

    def clue_timelines_before(self, chapter_id: str) -> tuple[ClueTimeline, ...]:
        with self.project.database.connect() as connection:
            clue_rows = connection.execute(
                """
                SELECT * FROM narrative_clues
                WHERE status = 'CURRENT' AND review_status IN ('APPROVED', 'LOCKED')
                ORDER BY created_at, id
                """
            ).fetchall()
            event_rows = connection.execute(
                """
                WITH target AS (
                    SELECT v.sort_index AS volume_order, c.sort_index AS chapter_order
                    FROM chapters c JOIN volumes v ON v.id = c.volume_id WHERE c.id = ?
                )
                SELECT e.* FROM narrative_clue_events e
                JOIN chapters c ON c.id = e.chapter_id
                JOIN volumes v ON v.id = c.volume_id
                CROSS JOIN target t
                WHERE e.review_status IN ('APPROVED', 'LOCKED')
                  AND (v.sort_index < t.volume_order OR
                       (v.sort_index = t.volume_order AND c.sort_index < t.chapter_order))
                ORDER BY v.sort_index, c.sort_index, e.created_at, e.id
                """,
                (chapter_id,),
            ).fetchall()
        events: dict[str, list[NarrativeClueEvent]] = {}
        for row in event_rows:
            events.setdefault(row["clue_id"], []).append(self._clue_event(row))
        return tuple(
            ClueTimeline(self._clue(row), tuple(events.get(row["id"], [])))
            for row in clue_rows
        )

    def update_clue_detail(
        self,
        clue_id: str,
        detail: str,
        source_type: SourceType,
    ) -> NarrativeClue:
        clue = self.get_clue(clue_id)
        if clue.review_status == ReviewStatus.LOCKED:
            raise ProtectedMemoryError("锁定的叙事线索不能直接修改")
        if source_type == SourceType.MODEL and clue.authority == Authority.USER_CONFIRMED:
            raise ProtectedMemoryError("模型不能覆盖用户确认的叙事线索")
        if not detail.strip():
            raise ValueError("叙事线索详情不能为空")
        with self.project.database.connect() as connection, connection:
            connection.execute(
                "UPDATE narrative_clues SET detail = ?, updated_at = ? WHERE id = ?",
                (detail.strip(), _now().isoformat(), clue_id),
            )
        return self.get_clue(clue_id)

    @staticmethod
    def _canon(row: sqlite3.Row) -> CanonEntry:
        return CanonEntry(
            row["id"],
            row["title"],
            row["detail"],
            row["source_chapter_id"],
            row["source_paragraph_id"],
            float(row["confidence"]),
            Authority(row["authority"]),
            MemoryStatus(row["status"]),
            ReviewStatus(row["review_status"]),
            _time(row["created_at"]),
            CanonCategory(row["category"]) if row["category"] else None,
        )

    @staticmethod
    def _clue(row: sqlite3.Row) -> NarrativeClue:
        return NarrativeClue(
            row["id"],
            ClueType(row["clue_type"]),
            row["title"],
            row["detail"],
            Authority(row["authority"]),
            MemoryStatus(row["status"]),
            ReviewStatus(row["review_status"]),
            _time(row["created_at"]),
        )

    @staticmethod
    def _clue_event(row: sqlite3.Row) -> NarrativeClueEvent:
        return NarrativeClueEvent(
            row["id"],
            row["clue_id"],
            row["chapter_id"],
            ClueAction(row["action"]),
            row["detail"],
            SourceType(row["source_type"]),
            ReviewStatus(row["review_status"]),
            _time(row["created_at"]),
        )
