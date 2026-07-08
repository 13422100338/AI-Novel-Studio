from __future__ import annotations

import sqlite3
from datetime import UTC, datetime

from ai_novel_studio.domain.generation import CreationMode, GenerationRun, GenerationStatus
from ai_novel_studio.domain.identifiers import new_id
from ai_novel_studio.infrastructure.storage.project_repository import ProjectRepository


class ActiveGenerationError(RuntimeError):
    pass


class GenerationStateError(RuntimeError):
    pass


LEGAL_GENERATION_TRANSITIONS = {
    GenerationStatus.PREPARING: {
        GenerationStatus.READY,
        GenerationStatus.FAILED,
        GenerationStatus.DISCARDED,
    },
    GenerationStatus.READY: {
        GenerationStatus.STREAMING,
        GenerationStatus.FAILED,
        GenerationStatus.DISCARDED,
    },
    GenerationStatus.STREAMING: {
        GenerationStatus.PARTIAL,
        GenerationStatus.COMPLETED,
        GenerationStatus.FAILED,
        GenerationStatus.DISCARDED,
    },
    GenerationStatus.PARTIAL: {
        GenerationStatus.ACCEPTED,
        GenerationStatus.DISCARDED,
    },
    GenerationStatus.COMPLETED: {
        GenerationStatus.ACCEPTED,
        GenerationStatus.DISCARDED,
    },
    GenerationStatus.FAILED: {GenerationStatus.DISCARDED},
    GenerationStatus.ACCEPTED: set(),
    GenerationStatus.DISCARDED: set(),
}

_UPDATABLE_FIELDS = {
    "context_manifest_id",
    "accepted_chapter_revision",
    "input_tokens",
    "output_tokens",
    "cached_input_tokens",
    "reasoning_tokens",
    "failure_code",
    "failure_message",
}


def _now() -> datetime:
    return datetime.now(UTC)


class GenerationRepository:

    def __init__(self, project: ProjectRepository) -> None:
        self.project = project

    def create_preparing(
        self,
        *,
        chapter_id: str,
        mode: CreationMode,
        brief_id: str | None,
        brief_revision: int | None,
        model_provider_id: str,
        model_id: str,
        output_token_limit: int,
        prompt_version: str,
    ) -> GenerationRun:
        run_id = new_id()
        now = _now().isoformat()
        try:
            with self.project.database.connect() as connection, connection:
                connection.execute(
                    """
                    INSERT INTO generation_runs(
                        id, chapter_id, mode, status, brief_id, brief_revision,
                        context_manifest_id, model_provider_id, model_id,
                        output_token_limit, prompt_version, accepted_chapter_revision,
                        input_tokens, output_tokens, cached_input_tokens, reasoning_tokens,
                        failure_code, failure_message, started_at, updated_at,
                        completed_at, accepted_at
                    ) VALUES (?, ?, ?, 'PREPARING', ?, ?, NULL, ?, ?, ?, ?,
                              NULL, NULL, NULL, NULL, NULL, NULL, NULL, ?, ?, NULL, NULL)
                    """,
                    (
                        run_id,
                        chapter_id,
                        mode.value,
                        brief_id,
                        brief_revision,
                        model_provider_id,
                        model_id,
                        output_token_limit,
                        prompt_version,
                        now,
                        now,
                    ),
                )
        except sqlite3.IntegrityError as error:
            if "generation_one_active_writer" in str(error) or "UNIQUE constraint" in str(
                error
            ):
                raise ActiveGenerationError("当前章节已有活动中的生成任务") from error
            raise
        return self.get(run_id)

    def mark_ready(self, run_id: str, context_manifest_id: str) -> GenerationRun:
        return self.transition(
            run_id,
            GenerationStatus.PREPARING,
            GenerationStatus.READY,
            context_manifest_id=context_manifest_id,
        )

    def fail_preparation(self, run_id: str, code: str, message: str) -> GenerationRun:
        return self.transition(
            run_id,
            GenerationStatus.PREPARING,
            GenerationStatus.FAILED,
            failure_code=code,
            failure_message=message,
        )

    def transition(
        self,
        run_id: str,
        expected_status: GenerationStatus,
        target_status: GenerationStatus,
        **fields: object,
    ) -> GenerationRun:
        unsupported = set(fields) - _UPDATABLE_FIELDS
        if unsupported:
            raise ValueError(f"不支持的更新字段：{', '.join(sorted(unsupported))}")
        if target_status not in LEGAL_GENERATION_TRANSITIONS[expected_status]:
            raise GenerationStateError(
                f"非法生成状态转换：{expected_status.value} -> {target_status.value}"
            )
        if target_status == GenerationStatus.READY and not fields.get(
            "context_manifest_id"
        ):
            raise GenerationStateError("READY 状态必须绑定 Context Manifest")
        if target_status == GenerationStatus.ACCEPTED and fields.get(
            "accepted_chapter_revision"
        ) is None:
            raise GenerationStateError("ACCEPTED 状态必须记录采用的章节修订")

        now = _now().isoformat()
        assignments = ["status = ?", "updated_at = ?"]
        values: list[object] = [target_status.value, now]
        for field, value in fields.items():
            assignments.append(f"{field} = ?")
            values.append(value)
        if target_status in {
            GenerationStatus.PARTIAL,
            GenerationStatus.COMPLETED,
            GenerationStatus.FAILED,
            GenerationStatus.DISCARDED,
        }:
            assignments.append("completed_at = ?")
            values.append(now)
        if target_status == GenerationStatus.ACCEPTED:
            assignments.append("accepted_at = ?")
            values.append(now)
        values.extend((run_id, expected_status.value))
        with self.project.database.connect() as connection, connection:
            cursor = connection.execute(
                f"UPDATE generation_runs SET {', '.join(assignments)} "
                "WHERE id = ? AND status = ?",
                tuple(values),
            )
        if cursor.rowcount != 1:
            current = self.get(run_id)
            raise GenerationStateError(
                f"生成任务状态已变化：预期 {expected_status.value}，"
                f"当前 {current.status.value}"
            )
        return self.get(run_id)

    def list_by_statuses(
        self, statuses: tuple[GenerationStatus, ...]
    ) -> tuple[GenerationRun, ...]:
        if not statuses:
            return ()
        placeholders = ", ".join("?" for _ in statuses)
        with self.project.database.connect() as connection:
            rows = connection.execute(
                f"SELECT * FROM generation_runs WHERE status IN ({placeholders}) "
                "ORDER BY started_at, id",
                tuple(status.value for status in statuses),
            ).fetchall()
        return tuple(self._run_from_row(row) for row in rows)

    def get(self, run_id: str) -> GenerationRun:
        with self.project.database.connect() as connection:
            row = connection.execute(
                "SELECT * FROM generation_runs WHERE id = ?", (run_id,)
            ).fetchone()
        if row is None:
            raise KeyError(f"unknown generation run: {run_id}")
        return self._run_from_row(row)

    @staticmethod
    def _run_from_row(row: sqlite3.Row) -> GenerationRun:
        return GenerationRun(
            id=row["id"],
            chapter_id=row["chapter_id"],
            mode=CreationMode(row["mode"]),
            status=GenerationStatus(row["status"]),
            brief_id=row["brief_id"],
            brief_revision=row["brief_revision"],
            context_manifest_id=row["context_manifest_id"],
            model_provider_id=row["model_provider_id"],
            model_id=row["model_id"],
            output_token_limit=row["output_token_limit"],
            prompt_version=row["prompt_version"],
            accepted_chapter_revision=row["accepted_chapter_revision"],
            input_tokens=row["input_tokens"],
            output_tokens=row["output_tokens"],
            cached_input_tokens=row["cached_input_tokens"],
            reasoning_tokens=row["reasoning_tokens"],
            failure_code=row["failure_code"],
            failure_message=row["failure_message"],
            started_at=datetime.fromisoformat(row["started_at"]),
            updated_at=datetime.fromisoformat(row["updated_at"]),
            completed_at=(
                datetime.fromisoformat(row["completed_at"]) if row["completed_at"] else None
            ),
            accepted_at=(
                datetime.fromisoformat(row["accepted_at"]) if row["accepted_at"] else None
            ),
        )
