import sqlite3

import pytest

from ai_novel_studio.infrastructure.storage.migration_manager import (
    LATEST_SCHEMA_VERSION,
    MigrationManager,
)


def _migrated() -> sqlite3.Connection:
    connection = sqlite3.connect(":memory:")
    connection.row_factory = sqlite3.Row
    MigrationManager(connection).migrate()
    return connection


def test_schema_v23_adds_project_constitutions() -> None:
    connection = _migrated()
    tables = {
        row["name"]
        for row in connection.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table'"
        ).fetchall()
    }
    indexes = {
        row["name"]
        for row in connection.execute(
            "SELECT name FROM sqlite_master WHERE type = 'index'"
        ).fetchall()
    }
    assert LATEST_SCHEMA_VERSION == 25
    assert "project_constitutions" in tables
    assert "project_constitutions_project" in indexes


def test_constitution_schema_enforces_check_and_unique() -> None:
    connection = _migrated()
    with pytest.raises(sqlite3.IntegrityError):
        connection.execute(
            "INSERT INTO project_constitutions("
            "id, project_id, revision, approved_by_author, created_at"
            ") VALUES ('c1', 'p1', 0, 1, 't')"
        )
    with pytest.raises(sqlite3.IntegrityError):
        connection.execute(
            "INSERT INTO project_constitutions("
            "id, project_id, revision, approved_by_author, created_at"
            ") VALUES ('c1', 'p1', 1, 2, 't')"
        )
    connection.execute(
        "INSERT INTO project_constitutions("
        "id, project_id, revision, approved_by_author, created_at"
        ") VALUES ('c1', 'p1', 1, 1, 't')"
    )
    with pytest.raises(sqlite3.IntegrityError):
        connection.execute(
            "INSERT INTO project_constitutions("
            "id, project_id, revision, approved_by_author, created_at"
            ") VALUES ('c2', 'p1', 1, 1, 't')"
        )


def test_constitution_schema_enforces_project_fk() -> None:
    connection = _migrated()
    connection.execute("PRAGMA foreign_keys = ON")
    with pytest.raises(sqlite3.IntegrityError):
        connection.execute(
            "INSERT INTO project_constitutions("
            "id, project_id, revision, approved_by_author, created_at"
            ") VALUES ('c1', 'missing-project', 1, 1, 't')"
        )
