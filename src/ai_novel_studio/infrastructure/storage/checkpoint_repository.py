from __future__ import annotations

import hashlib
import sqlite3
from datetime import UTC, datetime
from pathlib import Path

from ai_novel_studio.domain.generation import GenerationCheckpoint, GenerationStatus
from ai_novel_studio.domain.identifiers import new_id
from ai_novel_studio.infrastructure.storage.atomic_file import atomic_write_text
from ai_novel_studio.infrastructure.storage.generation_repository import GenerationRepository
from ai_novel_studio.infrastructure.storage.project_repository import ProjectRepository


class CheckpointContentError(ValueError):
    pass


class CheckpointIntegrityError(RuntimeError):
    pass


def _hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


class CheckpointRepository:
    def __init__(
        self, project: ProjectRepository, runs: GenerationRepository | None = None
    ) -> None:
        self.project = project
        self.runs = runs or GenerationRepository(project)

    def append(
        self, run_id: str, text: str, finish_reason: str | None = None
    ) -> GenerationCheckpoint:
        if not text:
            raise CheckpointContentError("检查点正文不能为空")
        run = self.runs.get(run_id)
        if run.status != GenerationStatus.STREAMING:
            raise CheckpointContentError("只有 STREAMING 任务可以追加检查点")

        connection = self.project.database.connect()
        path: Path | None = None
        wrote_new_file = False
        try:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                """
                SELECT * FROM generation_checkpoints
                WHERE run_id = ? ORDER BY sequence DESC LIMIT 1
                """,
                (run_id,),
            ).fetchone()
            if row is None:
                sequence = 0
            else:
                previous = self._checkpoint(row)
                previous_text = self._verified_text(previous)
                if not text.startswith(previous_text) or len(text) <= len(previous_text):
                    raise CheckpointContentError("新检查点必须是上一检查点的累计增长文本")
                sequence = previous.sequence + 1

            checkpoint_id = new_id()
            relative = (
                Path(".ai_pipeline")
                / "checkpoints"
                / f"run_{run_id}"
                / f"checkpoint_{sequence}.md"
            )
            path = self.project.layout.root / relative
            if path.exists():
                raise FileExistsError(f"检查点文件已存在：{relative.as_posix()}")
            atomic_write_text(path, text)
            wrote_new_file = True
            created_at = datetime.now(UTC)
            connection.execute(
                "INSERT INTO generation_checkpoints VALUES (?, ?, ?, ?, ?, ?, ?)",
                (
                    checkpoint_id,
                    run_id,
                    sequence,
                    relative.as_posix(),
                    _hash(text),
                    finish_reason,
                    created_at.isoformat(),
                ),
            )
            connection.commit()
        except BaseException:
            connection.rollback()
            if path is not None and wrote_new_file:
                path.unlink(missing_ok=True)
            raise
        finally:
            connection.close()
        return self.get(checkpoint_id)

    def get(self, checkpoint_id: str) -> GenerationCheckpoint:
        with self.project.database.connect() as connection:
            row = connection.execute(
                "SELECT * FROM generation_checkpoints WHERE id = ?", (checkpoint_id,)
            ).fetchone()
        if row is None:
            raise KeyError(f"unknown generation checkpoint: {checkpoint_id}")
        return self._checkpoint(row)

    def latest(self, run_id: str) -> GenerationCheckpoint | None:
        with self.project.database.connect() as connection:
            row = connection.execute(
                """
                SELECT * FROM generation_checkpoints
                WHERE run_id = ? ORDER BY sequence DESC LIMIT 1
                """,
                (run_id,),
            ).fetchone()
        if row is None:
            return None
        checkpoint = self._checkpoint(row)
        self._verified_text(checkpoint)
        return checkpoint

    def read(self, checkpoint_id: str) -> str:
        return self._verified_text(self.get(checkpoint_id))

    def _verified_text(self, checkpoint: GenerationCheckpoint) -> str:
        root = self.project.layout.root.resolve()
        path = (root / checkpoint.text_path).resolve()
        if not path.is_relative_to(root):
            raise CheckpointIntegrityError("检查点路径越出项目目录")
        if not path.is_file():
            raise CheckpointIntegrityError("检查点文件不存在")
        text = path.read_text(encoding="utf-8")
        if _hash(text) != checkpoint.content_hash:
            raise CheckpointIntegrityError("检查点正文哈希不匹配")
        return text

    @staticmethod
    def _checkpoint(row: sqlite3.Row) -> GenerationCheckpoint:
        return GenerationCheckpoint(
            id=row["id"],
            run_id=row["run_id"],
            sequence=row["sequence"],
            text_path=row["text_path"],
            content_hash=row["content_hash"],
            finish_reason=row["finish_reason"],
            created_at=datetime.fromisoformat(row["created_at"]),
        )
