from __future__ import annotations

import sqlite3
from datetime import UTC, datetime

from ai_novel_studio.domain.identifiers import new_id
from ai_novel_studio.domain.memory import Authority, ReviewStatus, SourceType
from ai_novel_studio.domain.view import (
    EpistemicStatus,
    ViewAssertion,
    ViewAssertionDraft,
    ViewType,
)
from ai_novel_studio.infrastructure.storage.project_repository import ProjectRepository


class ViewAssertionRepositoryError(RuntimeError):
    pass


class ViewAssertionRepository:
    def __init__(self, project: ProjectRepository) -> None:
        self.project = project

    def create(
        self,
        draft: ViewAssertionDraft,
        *,
        authority: Authority,
        review_status: ReviewStatus,
        source_type: SourceType,
        source_id: str,
        source_revision: int,
    ) -> ViewAssertion:
        normalized_source_id = source_id.strip()
        if not normalized_source_id or len(normalized_source_id) > 500:
            raise ValueError("source_id must contain 1 to 500 characters")
        if (
            isinstance(source_revision, bool)
            or not isinstance(source_revision, int)
            or source_revision < 0
        ):
            raise ValueError("source_revision must be a non-negative integer")
        assertion_id = new_id()
        now = datetime.now(UTC).isoformat()
        with self.project.database.connect() as connection, connection:
            self._require_active_character(connection, draft.subject_id, "subject_id")
            if draft.viewer_subject_id is not None:
                self._require_active_character(
                    connection,
                    draft.viewer_subject_id,
                    "viewer_subject_id",
                )
            connection.execute(
                """
                INSERT INTO view_assertions (
                    id, subject_id, view_type, viewer_subject_id,
                    epistemic_status, content, valid_from_sequence,
                    valid_to_sequence, story_time_label,
                    narrative_visible_from_sequence,
                    narrative_visible_to_sequence, authority, review_status,
                    source_type, source_id, source_revision, stale,
                    source_changed, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                          0, 0, ?, ?)
                """,
                (
                    assertion_id,
                    draft.subject_id,
                    draft.view_type.value,
                    draft.viewer_subject_id,
                    draft.epistemic_status.value
                    if draft.epistemic_status is not None
                    else None,
                    draft.content,
                    draft.valid_from_sequence,
                    draft.valid_to_sequence,
                    draft.story_time_label,
                    draft.narrative_visible_from_sequence,
                    draft.narrative_visible_to_sequence,
                    authority.value,
                    review_status.value,
                    source_type.value,
                    normalized_source_id,
                    source_revision,
                    now,
                    now,
                ),
            )
        return self.get(assertion_id)

    @staticmethod
    def invalidate_source_revision_in_connection(
        connection: sqlite3.Connection,
        *,
        source_id: str,
        new_revision: int,
        updated_at: str,
    ) -> None:
        connection.execute(
            """
            UPDATE view_assertions
            SET source_changed = 1, updated_at = ?
            WHERE source_id = ?
              AND source_revision != ?
              AND review_status IN ('APPROVED', 'LOCKED')
              AND source_changed = 0
            """,
            (updated_at, source_id, new_revision),
        )
        connection.execute(
            """
            UPDATE view_assertions
            SET stale = 1, updated_at = ?
            WHERE source_id = ?
              AND source_revision != ?
              AND review_status NOT IN ('APPROVED', 'LOCKED')
              AND stale = 0
            """,
            (updated_at, source_id, new_revision),
        )

    def get(self, assertion_id: str) -> ViewAssertion:
        with self.project.database.connect() as connection:
            row = connection.execute(
                "SELECT * FROM view_assertions WHERE id = ?",
                (assertion_id,),
            ).fetchone()
        if row is None:
            raise KeyError(f"unknown view assertion: {assertion_id}")
        return self._assertion(row)

    def list_model_review_candidates(
        self, *, limit: int = 100
    ) -> tuple[ViewAssertion, ...]:
        if isinstance(limit, bool) or not isinstance(limit, int):
            raise ValueError("limit must be an integer")
        if limit < 1:
            return ()
        bounded_limit = min(limit, 500)
        with self.project.database.connect() as connection:
            rows = connection.execute(
                """
                SELECT va.*
                FROM view_assertions va
                JOIN subjects subject
                  ON subject.id = va.subject_id
                 AND subject.type = 'CHARACTER'
                 AND subject.active = 1
                WHERE va.authority = 'MODEL_EXTRACTED'
                  AND va.source_type = 'MODEL'
                  AND va.review_status = 'REVIEW'
                  AND va.stale = 0
                  AND va.source_changed = 0
                ORDER BY va.created_at, va.id
                LIMIT ?
                """,
                (bounded_limit,),
            ).fetchall()
        return tuple(self._assertion(row) for row in rows)

    def review_model_candidate(
        self,
        assertion_id: str,
        *,
        decision: ReviewStatus,
    ) -> ViewAssertion:
        if decision not in {ReviewStatus.APPROVED, ReviewStatus.REJECTED}:
            raise ValueError("model candidate decision must be APPROVED or REJECTED")
        now = datetime.now(UTC).isoformat()
        with self.project.database.connect() as connection, connection:
            row = connection.execute(
                "SELECT * FROM view_assertions WHERE id = ?",
                (assertion_id,),
            ).fetchone()
            if row is None:
                raise KeyError(f"unknown view assertion: {assertion_id}")
            if (
                row["authority"] != Authority.MODEL_EXTRACTED.value
                or row["source_type"] != SourceType.MODEL.value
            ):
                raise ViewAssertionRepositoryError("只有模型提取候选可以执行此审查")
            if bool(row["stale"]) or bool(row["source_changed"]):
                raise ViewAssertionRepositoryError("候选来源已经变化，需要重新生成")
            if row["review_status"] != ReviewStatus.REVIEW.value:
                raise ViewAssertionRepositoryError("候选已经完成审查，不能重复审查")
            cursor = connection.execute(
                """
                UPDATE view_assertions
                SET review_status = ?, updated_at = ?
                WHERE id = ?
                  AND authority = 'MODEL_EXTRACTED'
                  AND source_type = 'MODEL'
                  AND review_status = 'REVIEW'
                  AND stale = 0
                  AND source_changed = 0
                  AND updated_at = ?
                """,
                (decision.value, now, assertion_id, row["updated_at"]),
            )
            if cursor.rowcount != 1:
                raise ViewAssertionRepositoryError("候选在审查期间发生变化，请重新载入")
        return self.get(assertion_id)

    def list_visible_at(
        self,
        *,
        narrative_sequence: int,
        view_type: ViewType,
        viewer_subject_id: str | None = None,
    ) -> tuple[ViewAssertion, ...]:
        self._validate_context_query(
            narrative_sequence=narrative_sequence,
            view_type=view_type,
            viewer_subject_id=viewer_subject_id,
        )
        with self.project.database.connect() as connection:
            if viewer_subject_id is not None:
                self._require_active_character(
                    connection,
                    viewer_subject_id,
                    "viewer_subject_id",
                )
            rows = connection.execute(
                """
                SELECT va.*
                FROM view_assertions va
                JOIN subjects subject
                  ON subject.id = va.subject_id
                 AND subject.type = 'CHARACTER'
                 AND subject.active = 1
                WHERE va.view_type = ?
                  AND va.viewer_subject_id IS ?
                  AND va.review_status IN ('APPROVED', 'LOCKED')
                  AND va.stale = 0
                  AND va.source_changed = 0
                  AND (va.valid_from_sequence IS NULL
                       OR va.valid_from_sequence <= ?)
                  AND (va.valid_to_sequence IS NULL
                       OR va.valid_to_sequence >= ?)
                  AND (va.narrative_visible_from_sequence IS NULL
                       OR va.narrative_visible_from_sequence <= ?)
                  AND (va.narrative_visible_to_sequence IS NULL
                       OR va.narrative_visible_to_sequence >= ?)
                ORDER BY va.subject_id, va.created_at, va.id
                """,
                (
                    view_type.value,
                    viewer_subject_id,
                    narrative_sequence,
                    narrative_sequence,
                    narrative_sequence,
                    narrative_sequence,
                ),
            ).fetchall()
        return tuple(self._assertion(row) for row in rows)

    @staticmethod
    def _require_active_character(
        connection: sqlite3.Connection,
        subject_id: str,
        field: str,
    ) -> None:
        row = connection.execute(
            "SELECT 1 FROM subjects "
            "WHERE id = ? AND type = 'CHARACTER' AND active = 1",
            (subject_id,),
        ).fetchone()
        if row is None:
            raise KeyError(f"{field} is unknown, inactive, or not a character")

    @staticmethod
    def _validate_context_query(
        *,
        narrative_sequence: int,
        view_type: ViewType,
        viewer_subject_id: str | None,
    ) -> None:
        if (
            isinstance(narrative_sequence, bool)
            or not isinstance(narrative_sequence, int)
            or narrative_sequence < 0
        ):
            raise ValueError("narrative_sequence must be a non-negative integer")
        if view_type == ViewType.CHARACTER_VIEW:
            if viewer_subject_id is None or not viewer_subject_id.strip():
                raise ValueError("CHARACTER_VIEW requires viewer_subject_id")
        elif viewer_subject_id is not None:
            raise ValueError("viewer_subject_id belongs only to CHARACTER_VIEW")

    @staticmethod
    def _assertion(row: sqlite3.Row) -> ViewAssertion:
        epistemic_status = row["epistemic_status"]
        return ViewAssertion(
            id=str(row["id"]),
            subject_id=str(row["subject_id"]),
            view_type=ViewType(str(row["view_type"])),
            viewer_subject_id=str(row["viewer_subject_id"])
            if row["viewer_subject_id"] is not None
            else None,
            epistemic_status=EpistemicStatus(str(epistemic_status))
            if epistemic_status is not None
            else None,
            content=str(row["content"]),
            valid_from_sequence=row["valid_from_sequence"],
            valid_to_sequence=row["valid_to_sequence"],
            story_time_label=str(row["story_time_label"])
            if row["story_time_label"] is not None
            else None,
            narrative_visible_from_sequence=row[
                "narrative_visible_from_sequence"
            ],
            narrative_visible_to_sequence=row["narrative_visible_to_sequence"],
            authority=Authority(str(row["authority"])),
            review_status=ReviewStatus(str(row["review_status"])),
            source_type=SourceType(str(row["source_type"])),
            source_id=str(row["source_id"]),
            source_revision=int(row["source_revision"]),
            stale=bool(row["stale"]),
            source_changed=bool(row["source_changed"]),
            created_at=datetime.fromisoformat(str(row["created_at"])),
            updated_at=datetime.fromisoformat(str(row["updated_at"])),
        )
