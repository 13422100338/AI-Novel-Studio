import sqlite3
from pathlib import Path

import pytest

from ai_novel_studio.infrastructure.storage.migration_manager import MIGRATIONS, MigrationManager
from ai_novel_studio.infrastructure.storage.project_repository import ProjectRepository


def test_new_project_has_outline_tables(tmp_path: Path) -> None:
    project = ProjectRepository.create(tmp_path / "novel", "Outline")
    with project.database.connect() as connection:
        tables = {
            row[0]
            for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")
        }
        assert {"outline_documents", "outline_versions"} <= tables
        assert connection.execute("PRAGMA user_version").fetchone()[0] == 27
        assert connection.execute("PRAGMA foreign_key_check").fetchall() == []


def test_upgrade_from_v25_preserves_author_data() -> None:
    with sqlite3.connect(":memory:") as connection:
        connection.execute("PRAGMA foreign_keys = ON")
        for version in range(1, 26):
            MIGRATIONS[version](connection)
        connection.execute("PRAGMA user_version = 25")
        connection.execute("INSERT INTO projects VALUES ('p', '旧项目', 1, 't', 't')")
        connection.execute("INSERT INTO project_guidance VALUES ('p', '原样保留\r\n', 3, 't')")
        connection.commit()
        MigrationManager(connection).migrate()
        assert connection.execute("SELECT * FROM projects").fetchall() == [
            ("p", "旧项目", 1, "t", "t")
        ]
        assert connection.execute("SELECT * FROM project_guidance").fetchall() == [
            ("p", "原样保留\r\n", 3, "t")
        ]
        assert connection.execute("SELECT COUNT(*) FROM outline_documents").fetchone()[0] == 0
        assert connection.execute("PRAGMA user_version").fetchone()[0] == 27
        assert connection.execute("PRAGMA foreign_key_check").fetchall() == []


def test_outline_schema_rejects_invalid_revision_and_foreign_document(tmp_path: Path) -> None:
    project = ProjectRepository.create(tmp_path / "novel", "Outline")
    with project.database.connect() as connection:
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute(
                "INSERT INTO outline_documents VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                ("d", project.project.id, "全书", 0, 0, "a" * 64, "t", "t"),
            )
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute(
                "INSERT INTO outline_versions VALUES (?, ?, ?, ?, ?)",
                ("v", "missing", 1, "a" * 64, "t"),
            )
