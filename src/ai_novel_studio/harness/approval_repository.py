from __future__ import annotations

import json
import sqlite3
from datetime import UTC, datetime

from ai_novel_studio.domain.identifiers import new_id
from ai_novel_studio.harness.approvals import (
    ApprovalKind,
    ApprovalRequest,
    ApprovalStatus,
)
from ai_novel_studio.infrastructure.storage.project_repository import ProjectRepository


def _now() -> datetime:
    return datetime.now(UTC)


class ApprovalRepository:
    """SQLite persistence for harness approval records (schema v22)."""

    def __init__(self, project: ProjectRepository) -> None:
        self.project = project

    def create(
        self,
        *,
        run_id: str,
        kind: ApprovalKind,
        summary: str,
        payload: dict[str, object],
        expected_revisions: tuple[tuple[str, int], ...],
        idempotency_key: str,
    ) -> ApprovalRequest:
        request_id = new_id()
        now = _now().isoformat()
        with self.project.database.connect() as connection, connection:
            connection.execute(
                """
                INSERT INTO harness_approvals(
                    id, run_id, kind, summary, payload_json,
                    expected_revisions_json, idempotency_key, status, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, 'PENDING', ?)
                """,
                (
                    request_id,
                    run_id,
                    kind.value,
                    summary,
                    json.dumps(payload, ensure_ascii=False),
                    json.dumps(expected_revisions, ensure_ascii=False),
                    idempotency_key,
                    now,
                ),
            )
        return self.get(request_id)

    def get(self, request_id: str) -> ApprovalRequest:
        with self.project.database.connect() as connection:
            row = connection.execute(
                "SELECT * FROM harness_approvals WHERE id = ?", (request_id,)
            ).fetchone()
        if row is None:
            raise KeyError(f"unknown approval request: {request_id}")
        return self._from_row(row)

    def get_by_key(self, run_id: str, idempotency_key: str) -> ApprovalRequest | None:
        with self.project.database.connect() as connection:
            row = connection.execute(
                "SELECT * FROM harness_approvals WHERE run_id = ? AND idempotency_key = ?",
                (run_id, idempotency_key),
            ).fetchone()
        return self._from_row(row) if row is not None else None

    def list_for_run(self, run_id: str) -> tuple[ApprovalRequest, ...]:
        with self.project.database.connect() as connection:
            rows = connection.execute(
                "SELECT * FROM harness_approvals WHERE run_id = ? ORDER BY created_at, id",
                (run_id,),
            ).fetchall()
        return tuple(self._from_row(row) for row in rows)

    def resolve(
        self,
        request_id: str,
        status: ApprovalStatus,
        resolution_note: str | None,
    ) -> ApprovalRequest:
        now = _now().isoformat()
        with self.project.database.connect() as connection, connection:
            connection.execute(
                """
                UPDATE harness_approvals
                SET status = ?, resolved_at = ?, resolution_note = ?
                WHERE id = ?
                """,
                (status.value, now, resolution_note, request_id),
            )
        return self.get(request_id)

    @staticmethod
    def _from_row(row: sqlite3.Row) -> ApprovalRequest:
        expected_revisions: tuple[tuple[str, int], ...] = tuple(
            (str(item[0]), int(item[1]))
            for item in json.loads(row["expected_revisions_json"])
        )
        payload: dict[str, object] = json.loads(row["payload_json"])
        return ApprovalRequest(
            request_id=row["id"],
            run_id=row["run_id"],
            kind=ApprovalKind(row["kind"]),
            summary=row["summary"],
            payload=payload,
            expected_revisions=expected_revisions,
            idempotency_key=row["idempotency_key"],
            status=ApprovalStatus(row["status"]),
            created_at=datetime.fromisoformat(row["created_at"]),
            resolved_at=(
                datetime.fromisoformat(row["resolved_at"]) if row["resolved_at"] else None
            ),
            resolution_note=row["resolution_note"],
        )
