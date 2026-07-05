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


def _now() -> datetime:
    return datetime.now(UTC)


class GenerationRepository:
    """Minimal run persistence used during preparation; Task 6 extends transitions."""

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
        now = _now().isoformat()
        with self.project.database.connect() as connection, connection:
            cursor = connection.execute(
                """
                UPDATE generation_runs
                SET status = 'READY', context_manifest_id = ?, updated_at = ?
                WHERE id = ? AND status = 'PREPARING'
                """,
                (context_manifest_id, now, run_id),
            )
        if cursor.rowcount != 1:
            raise GenerationStateError("只有 PREPARING 任务可以进入 READY")
        return self.get(run_id)

    def fail_preparation(self, run_id: str, code: str, message: str) -> GenerationRun:
        now = _now().isoformat()
        with self.project.database.connect() as connection, connection:
            cursor = connection.execute(
                """
                UPDATE generation_runs
                SET status = 'FAILED', failure_code = ?, failure_message = ?,
                    updated_at = ?, completed_at = ?
                WHERE id = ? AND status = 'PREPARING'
                """,
                (code, message, now, now, run_id),
            )
        if cursor.rowcount != 1:
            raise GenerationStateError("只有 PREPARING 任务可以记录准备失败")
        return self.get(run_id)

    def get(self, run_id: str) -> GenerationRun:
        with self.project.database.connect() as connection:
            row = connection.execute(
                "SELECT * FROM generation_runs WHERE id = ?", (run_id,)
            ).fetchone()
        if row is None:
            raise KeyError(f"unknown generation run: {run_id}")
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
