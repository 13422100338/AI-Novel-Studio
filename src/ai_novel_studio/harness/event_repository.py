from __future__ import annotations

import json
import sqlite3
from datetime import UTC, datetime

from ai_novel_studio.domain.identifiers import new_id
from ai_novel_studio.harness.run_state import HarnessRun, RunEvent, RunEventType, RunStage
from ai_novel_studio.infrastructure.storage.project_repository import ProjectRepository


def _now() -> datetime:
    return datetime.now(UTC)


class HarnessEventRepository:
    """SQLite persistence for harness runs and their append-only event log."""

    def __init__(self, project: ProjectRepository) -> None:
        self.project = project

    def start_run(
        self, *, goal: str, active_chapter_id: str | None = None
    ) -> tuple[HarnessRun, RunEvent]:
        normalized_goal = goal.strip()
        if not normalized_goal:
            raise ValueError("goal cannot be empty")
        run_id = new_id()
        event_id = new_id()
        now = _now().isoformat()
        with self.project.database.connect() as connection, connection:
            connection.execute(
                """
                INSERT INTO harness_runs(id, goal, stage, active_chapter_id, created_at, updated_at)
                VALUES (?, ?, 'CREATED', ?, ?, ?)
                """,
                (run_id, normalized_goal, active_chapter_id, now, now),
            )
            connection.execute(
                """
                INSERT INTO harness_run_events(
                    id, run_id, sequence, event_type, schema_version, occurred_at,
                    causation_id, correlation_id, payload_json
                ) VALUES (?, ?, 0, 'RUN_CREATED', 1, ?, NULL, NULL, '{}')
                """,
                (event_id, run_id, now),
            )
        return self.get_run(run_id), self.get_event(event_id)

    def get_run(self, run_id: str) -> HarnessRun:
        with self.project.database.connect() as connection:
            row = connection.execute(
                "SELECT * FROM harness_runs WHERE id = ?", (run_id,)
            ).fetchone()
        if row is None:
            raise KeyError(f"unknown harness run: {run_id}")
        return self._run_from_row(row)

    def list_runs(self) -> tuple[HarnessRun, ...]:
        with self.project.database.connect() as connection:
            rows = connection.execute(
                "SELECT * FROM harness_runs ORDER BY created_at, id"
            ).fetchall()
        return tuple(self._run_from_row(row) for row in rows)

    def set_stage(
        self,
        run_id: str,
        stage: RunStage,
        *,
        failure_code: str | None = None,
        failure_message: str | None = None,
    ) -> HarnessRun:
        now = _now().isoformat()
        completed_at = (
            now
            if stage in {RunStage.COMPLETED, RunStage.CANCELLED, RunStage.FAILED}
            else None
        )
        with self.project.database.connect() as connection, connection:
            connection.execute(
                """
                UPDATE harness_runs
                SET stage = ?, updated_at = ?, completed_at = ?,
                    failure_code = ?, failure_message = ?
                WHERE id = ?
                """,
                (stage.value, now, completed_at, failure_code, failure_message, run_id),
            )
        return self.get_run(run_id)

    def insert_event(
        self,
        run_id: str,
        event_type: RunEventType,
        payload: dict[str, object],
        *,
        schema_version: int = 1,
        causation_id: str | None = None,
        correlation_id: str | None = None,
        event_id: str | None = None,
    ) -> RunEvent:
        final_event_id = event_id or new_id()
        now = _now().isoformat()
        payload_json = json.dumps(payload, ensure_ascii=False)
        with self.project.database.connect() as connection, connection:
            row = connection.execute(
                """
                SELECT COALESCE(MAX(sequence), -1) + 1 AS next
                FROM harness_run_events WHERE run_id = ?
                """,
                (run_id,),
            ).fetchone()
            sequence = int(row["next"])
            connection.execute(
                """
                INSERT INTO harness_run_events(
                    id, run_id, sequence, event_type, schema_version, occurred_at,
                    causation_id, correlation_id, payload_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    final_event_id,
                    run_id,
                    sequence,
                    event_type.value,
                    schema_version,
                    now,
                    causation_id,
                    correlation_id,
                    payload_json,
                ),
            )
        return self.get_event(final_event_id)

    def get_event(self, event_id: str) -> RunEvent:
        with self.project.database.connect() as connection:
            row = connection.execute(
                "SELECT * FROM harness_run_events WHERE id = ?", (event_id,)
            ).fetchone()
        if row is None:
            raise KeyError(f"unknown harness run event: {event_id}")
        return self._event_from_row(row)

    def list_events(self, run_id: str) -> tuple[RunEvent, ...]:
        with self.project.database.connect() as connection:
            rows = connection.execute(
                "SELECT * FROM harness_run_events WHERE run_id = ? ORDER BY sequence",
                (run_id,),
            ).fetchall()
        return tuple(self._event_from_row(row) for row in rows)

    @staticmethod
    def _run_from_row(row: sqlite3.Row) -> HarnessRun:
        return HarnessRun(
            row["id"],
            row["goal"],
            RunStage(row["stage"]),
            row["active_chapter_id"],
            row["failure_code"],
            row["failure_message"],
            datetime.fromisoformat(row["created_at"]),
            datetime.fromisoformat(row["updated_at"]),
            datetime.fromisoformat(row["completed_at"]) if row["completed_at"] else None,
        )

    @staticmethod
    def _event_from_row(row: sqlite3.Row) -> RunEvent:
        payload: dict[str, object] = json.loads(row["payload_json"])
        return RunEvent(
            row["id"],
            row["run_id"],
            row["sequence"],
            RunEventType(row["event_type"]),
            row["schema_version"],
            datetime.fromisoformat(row["occurred_at"]),
            row["causation_id"],
            row["correlation_id"],
            payload,
        )
