import json
import sqlite3
from pathlib import Path

import pytest

from ai_novel_studio.infrastructure.storage.migration_manager import MigrationManager
from ai_novel_studio.infrastructure.storage.project_repository import ProjectRepository


def test_create_initializes_portable_project_and_default_volume(tmp_path: Path) -> None:
    root = tmp_path / "novel"

    repository = ProjectRepository.create(root, "My Novel")

    manifest = json.loads((root / "project.json").read_text(encoding="utf-8"))
    assert manifest == {
        "format_version": 1,
        "project_id": repository.project.id,
        "title": "My Novel",
    }
    assert (root / "project.sqlite3").is_file()
    assert (root / "manuscript").is_dir()
    assert (root / "backups").is_dir()
    assert (root / ".ai_pipeline" / "history").is_dir()
    volumes = repository.list_volumes()
    assert len(volumes) == 1
    assert volumes[0].title == "未分卷"


def test_schema_migration_is_idempotent(tmp_path: Path) -> None:
    repository = ProjectRepository.create(tmp_path / "novel", "My Novel")

    with repository.database.connect() as connection:
        MigrationManager(connection).migrate()
        MigrationManager(connection).migrate()
        version = connection.execute("PRAGMA user_version").fetchone()[0]
        rows = connection.execute("SELECT version FROM schema_migrations").fetchall()

    assert version == 1
    assert [row[0] for row in rows] == [1]


def test_open_restores_project_identity_and_structure(tmp_path: Path) -> None:
    root = tmp_path / "novel"
    created = ProjectRepository.create(root, "My Novel")

    reopened = ProjectRepository.open(root)

    assert reopened.project.id == created.project.id
    assert reopened.project.title == "My Novel"
    assert reopened.list_volumes() == created.list_volumes()


def test_create_rejects_non_empty_target(tmp_path: Path) -> None:
    root = tmp_path / "novel"
    root.mkdir()
    (root / "notes.txt").write_text("keep me", encoding="utf-8")

    with pytest.raises(FileExistsError, match="not empty"):
        ProjectRepository.create(root, "My Novel")


def test_open_rejects_database_with_future_schema(tmp_path: Path) -> None:
    root = tmp_path / "novel"
    repository = ProjectRepository.create(root, "My Novel")
    with sqlite3.connect(repository.layout.database) as connection:
        connection.execute("PRAGMA user_version = 99")

    with pytest.raises(RuntimeError, match="newer schema"):
        ProjectRepository.open(root)
