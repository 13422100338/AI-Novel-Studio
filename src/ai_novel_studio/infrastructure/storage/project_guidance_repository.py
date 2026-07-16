import sqlite3
from datetime import UTC, datetime

from ai_novel_studio.domain.project_guidance import ProjectGuidance
from ai_novel_studio.infrastructure.storage.project_repository import ProjectRepository


class ProjectGuidanceRepository:
    def __init__(self, project: ProjectRepository) -> None:
        self.project = project

    @property
    def project_id(self) -> str:
        return self.project.project.id

    def load(self) -> ProjectGuidance:
        with self.project.database.connect() as connection:
            row = connection.execute(
                "SELECT * FROM project_guidance WHERE project_id = ?",
                (self.project_id,),
            ).fetchone()
        if row is None:
            return ProjectGuidance(
                self.project_id,
                "",
                0,
                self.project.project.updated_at,
            )
        return self._guidance(row)

    def save_manual(
        self, highest_system_prompt: str, *, expected_revision: int
    ) -> ProjectGuidance:
        # This is user-authored canonical guidance; preserve it byte-for-byte instead
        # of applying the normalization used for model-generated records.
        normalized = highest_system_prompt
        now = datetime.now(UTC)
        with self.project.database.connect() as connection, connection:
            row = connection.execute(
                "SELECT * FROM project_guidance WHERE project_id = ?",
                (self.project_id,),
            ).fetchone()
            current_revision = int(row["revision"]) if row is not None else 0
            if current_revision != expected_revision:
                raise RuntimeError("小说最高提示已经被其他操作更新，请重新打开后再保存")
            if row is not None and row["highest_system_prompt"] == normalized:
                return self._guidance(row)
            if row is None:
                connection.execute(
                    "INSERT INTO project_guidance VALUES (?, ?, 1, ?)",
                    (self.project_id, normalized, now.isoformat()),
                )
            else:
                cursor = connection.execute(
                    "UPDATE project_guidance SET highest_system_prompt = ?, "
                    "revision = revision + 1, updated_at = ? "
                    "WHERE project_id = ? AND revision = ?",
                    (normalized, now.isoformat(), self.project_id, expected_revision),
                )
                if cursor.rowcount != 1:
                    raise RuntimeError("小说最高提示已经被其他操作更新，请重新打开后再保存")
            saved = connection.execute(
                "SELECT * FROM project_guidance WHERE project_id = ?",
                (self.project_id,),
            ).fetchone()
        if saved is None:  # pragma: no cover - guarded by the transaction above
            raise RuntimeError("小说最高提示保存失败")
        return self._guidance(saved)

    @staticmethod
    def _guidance(row: sqlite3.Row) -> ProjectGuidance:
        return ProjectGuidance(
            row["project_id"],
            row["highest_system_prompt"],
            int(row["revision"]),
            datetime.fromisoformat(row["updated_at"]),
        )
