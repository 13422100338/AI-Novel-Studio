import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from ai_novel_studio.domain.identifiers import new_id, validate_id
from ai_novel_studio.domain.project import Project
from ai_novel_studio.domain.volume import Volume
from ai_novel_studio.infrastructure.storage.database import Database
from ai_novel_studio.infrastructure.storage.migration_manager import MigrationManager
from ai_novel_studio.infrastructure.storage.project_layout import ProjectLayout

PROJECT_FORMAT_VERSION = 1


def _now() -> datetime:
    return datetime.now(UTC)


def _parse_time(value: str) -> datetime:
    return datetime.fromisoformat(value)


class ProjectRepository:
    def __init__(self, layout: ProjectLayout, database: Database, project: Project) -> None:
        self.layout = layout
        self.database = database
        self.project = project

    @classmethod
    def create(cls, root: Path, title: str) -> "ProjectRepository":
        layout = ProjectLayout.at(root)
        if layout.root.exists() and any(layout.root.iterdir()):
            raise FileExistsError(f"project target is not empty: {layout.root.name}")
        if not title.strip():
            raise ValueError("project title cannot be empty")
        layout.root.mkdir(parents=True, exist_ok=True)
        layout.create_directories()
        database = Database(layout.database)
        now = _now()
        project = Project(new_id(), title.strip(), PROJECT_FORMAT_VERSION, now, now)
        with database.connect() as connection:
            MigrationManager(connection).migrate()
            with connection:
                connection.execute(
                    "INSERT INTO projects VALUES (?, ?, ?, ?, ?)",
                    (
                        project.id,
                        project.title,
                        project.format_version,
                        now.isoformat(),
                        now.isoformat(),
                    ),
                )
                volume_id = new_id()
                connection.execute(
                    "INSERT INTO volumes VALUES (?, ?, ?, ?, ?, ?)",
                    (volume_id, "未分卷", "", 0, now.isoformat(), now.isoformat()),
                )
        manifest = {
            "format_version": PROJECT_FORMAT_VERSION,
            "project_id": project.id,
            "title": project.title,
        }
        temporary = layout.manifest.with_suffix(".json.tmp")
        temporary.write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        temporary.replace(layout.manifest)
        return cls(layout, database, project)

    @classmethod
    def open(cls, root: Path) -> "ProjectRepository":
        layout = ProjectLayout.at(root)
        if not layout.manifest.is_file() or not layout.database.is_file():
            raise FileNotFoundError("project.json or project.sqlite3 is missing")
        manifest: dict[str, Any] = json.loads(layout.manifest.read_text(encoding="utf-8"))
        project_id = validate_id(str(manifest["project_id"]))
        database = Database(layout.database)
        with database.connect() as connection:
            MigrationManager(connection).migrate()
            row = connection.execute(
                "SELECT * FROM projects WHERE id = ?", (project_id,)
            ).fetchone()
        if row is None:
            raise RuntimeError("project manifest identity is absent from database")
        project = Project(
            row["id"],
            row["title"],
            row["format_version"],
            _parse_time(row["created_at"]),
            _parse_time(row["updated_at"]),
        )
        return cls(layout, database, project)

    def list_volumes(self) -> list[Volume]:
        with self.database.connect() as connection:
            rows = connection.execute("SELECT * FROM volumes ORDER BY sort_index, id").fetchall()
        return [
            Volume(
                row["id"],
                row["title"],
                row["synopsis"],
                row["sort_index"],
                _parse_time(row["created_at"]),
                _parse_time(row["updated_at"]),
            )
            for row in rows
        ]

    def create_volume(self, title: str, synopsis: str = "") -> Volume:
        if not title.strip():
            raise ValueError("volume title cannot be empty")
        now = _now()
        with self.database.connect() as connection, connection:
            sort_index = int(
                connection.execute(
                    "SELECT COALESCE(MAX(sort_index), -1) + 1 FROM volumes"
                ).fetchone()[0]
            )
            volume = Volume(new_id(), title.strip(), synopsis, sort_index, now, now)
            connection.execute(
                "INSERT INTO volumes VALUES (?, ?, ?, ?, ?, ?)",
                (
                    volume.id,
                    volume.title,
                    volume.synopsis,
                    volume.sort_index,
                    now.isoformat(),
                    now.isoformat(),
                ),
            )
        return volume

    def rename_volume(self, volume_id: str, title: str) -> Volume:
        validate_id(volume_id)
        normalized = title.strip()
        if not normalized:
            raise ValueError("volume title cannot be empty")
        now = _now()
        with self.database.connect() as connection, connection:
            cursor = connection.execute(
                "UPDATE volumes SET title = ?, updated_at = ? WHERE id = ?",
                (normalized, now.isoformat(), volume_id),
            )
            if cursor.rowcount != 1:
                raise KeyError(f"unknown volume: {volume_id}")
        for volume in self.list_volumes():
            if volume.id == volume_id:
                return volume
        raise KeyError(f"unknown volume: {volume_id}")
