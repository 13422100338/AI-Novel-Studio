import hashlib
from dataclasses import dataclass

from ai_novel_studio.infrastructure.storage.project_repository import ProjectRepository


@dataclass(frozen=True, slots=True)
class IntegrityIssue:
    code: str
    message: str
    entity_id: str | None = None


@dataclass(frozen=True, slots=True)
class IntegrityReport:
    issues: tuple[IntegrityIssue, ...]

    @property
    def ok(self) -> bool:
        return not self.issues


class IntegrityChecker:
    def __init__(self, project: ProjectRepository) -> None:
        self._project = project

    def check(self) -> IntegrityReport:
        issues: list[IntegrityIssue] = []
        connection = self._project.database.connect()
        try:
            database_result = str(connection.execute("PRAGMA integrity_check").fetchone()[0])
            if database_result != "ok":
                issues.append(IntegrityIssue("database_integrity", database_result))
            rows = connection.execute(
                "SELECT id, content_path, content_hash FROM chapters "
                "WHERE is_deleted = 0 ORDER BY id"
            ).fetchall()
            version_rows = connection.execute(
                "SELECT id, content_snapshot_path, content_hash FROM chapter_versions ORDER BY id"
            ).fetchall()
        finally:
            connection.close()

        for row in rows:
            path = self._project.layout.root / row["content_path"]
            if not path.is_file():
                issues.append(
                    IntegrityIssue(
                        "chapter_content_missing", "canonical chapter content is missing", row["id"]
                    )
                )
                continue
            actual_hash = hashlib.sha256(path.read_bytes()).hexdigest()
            if actual_hash != row["content_hash"]:
                issues.append(
                    IntegrityIssue(
                        "chapter_hash_mismatch", "canonical chapter hash does not match", row["id"]
                    )
                )

        for row in version_rows:
            path = self._project.layout.root / row["content_snapshot_path"]
            if not path.is_file():
                issues.append(
                    IntegrityIssue(
                        "version_snapshot_missing", "chapter version is missing", row["id"]
                    )
                )
                continue
            if hashlib.sha256(path.read_bytes()).hexdigest() != row["content_hash"]:
                issues.append(
                    IntegrityIssue(
                        "version_hash_mismatch", "chapter version hash does not match", row["id"]
                    )
                )
        return IntegrityReport(tuple(issues))
