import sqlite3

import pytest

from ai_novel_studio.infrastructure.storage.migration_manager import (
    LATEST_SCHEMA_VERSION,
    MigrationManager,
    _migration_1,
    _migration_2,
)


def _legacy_v2_connection(path):  # type: ignore[no-untyped-def]
    connection = sqlite3.connect(path)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    with connection:
        connection.execute(
            "CREATE TABLE schema_migrations (version INTEGER PRIMARY KEY, "
            "applied_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)"
        )
        _migration_1(connection)
        _migration_2(connection)
        connection.execute("PRAGMA user_version = 2")
        connection.executemany(
            "INSERT INTO schema_migrations(version, applied_at) VALUES (?, ?)",
            ((1, "2026-07-03"), (2, "2026-07-03")),
        )
        connection.execute(
            "INSERT INTO projects VALUES (?, ?, ?, ?, ?)",
            ("project-1", "旧项目", 1, "2026-07-03", "2026-07-03"),
        )
        connection.execute(
            "INSERT INTO volumes VALUES (?, ?, ?, ?, ?, ?)",
            ("volume-1", "第一卷", "", 0, "2026-07-03", "2026-07-03"),
        )
        connection.execute(
            "INSERT INTO chapters VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                "chapter-1", "volume-1", "1", "旧章", "", "manuscript/chapter-1.md",
                "chapter-hash", 0, 0, "pending", 0, None, "2026-07-03", "2026-07-03",
            ),
        )
        connection.execute(
            "INSERT INTO canon_entries VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                "canon-1", "旧港状态", "已经封闭", "chapter-1", None, 1.0,
                "USER_CONFIRMED", "CURRENT", "LOCKED", "2026-07-03", "2026-07-03",
            ),
        )
    return connection


def test_latest_schema_keeps_generation_tables_and_preserves_v2_data(tmp_path) -> None:  # type: ignore[no-untyped-def]
    connection = _legacy_v2_connection(tmp_path / "legacy-v2.sqlite3")
    MigrationManager(connection).migrate()
    try:
        tables = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type IN ('table', 'view')"
            )
        }
        indexes = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'index'"
            )
        }
        title = connection.execute(
            "SELECT title FROM canon_entries WHERE id = 'canon-1'"
        ).fetchone()[0]
        version = connection.execute("PRAGMA user_version").fetchone()[0]
    finally:
        connection.close()

    assert version == LATEST_SCHEMA_VERSION == 4
    assert title == "旧港状态"
    assert {
        "chapter_requirements",
        "chapter_briefs",
        "brief_sources",
        "generation_runs",
        "generation_checkpoints",
    } <= tables
    assert "generation_one_active_writer" in indexes


def test_schema_v3_enforces_unique_requirement_checkpoint_and_active_writer(tmp_path) -> None:  # type: ignore[no-untyped-def]
    connection = _legacy_v2_connection(tmp_path / "constraints.sqlite3")
    MigrationManager(connection).migrate()
    with connection:
        connection.execute(
            "INSERT INTO chapter_requirements VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            ("req-1", "chapter-1", "要求", 0, 0, "hash", "2026-07-03", "2026-07-03"),
        )
        connection.execute(
            "INSERT INTO generation_runs "
            "(id, chapter_id, mode, status, model_provider_id, model_id, output_token_limit, "
            "prompt_version, started_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                "run-1", "chapter-1", "BASIC", "PREPARING", "provider", "model", 8000,
                "prose-v1", "2026-07-03", "2026-07-03",
            ),
        )
    with pytest.raises(sqlite3.IntegrityError):
        with connection:
            connection.execute(
                "INSERT INTO chapter_requirements VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                ("req-2", "chapter-1", "第二要求", 0, 0, "hash-2", "2026-07-03", "2026-07-03"),
            )
    with pytest.raises(sqlite3.IntegrityError):
        with connection:
            connection.execute(
                "INSERT INTO generation_runs "
                "(id, chapter_id, mode, status, model_provider_id, model_id, output_token_limit, "
                "prompt_version, started_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    "run-2", "chapter-1", "STANDARD", "STREAMING", "provider", "model", 8000,
                    "prose-v1", "2026-07-03", "2026-07-03",
                ),
            )
    with connection:
        connection.execute(
            "INSERT INTO generation_checkpoints VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                "checkpoint-1", "run-1", 0, ".ai_pipeline/checkpoints/run-1/0.md",
                "checkpoint-hash", None, "2026-07-03",
            ),
        )
    with pytest.raises(sqlite3.IntegrityError):
        with connection:
            connection.execute(
                "INSERT INTO generation_checkpoints VALUES (?, ?, ?, ?, ?, ?, ?)",
                (
                    "checkpoint-2", "run-1", 0,
                    ".ai_pipeline/checkpoints/run-1/duplicate.md", "other-hash", None,
                    "2026-07-03",
                ),
            )
    connection.close()


def test_schema_v3_migration_is_idempotent(tmp_path) -> None:  # type: ignore[no-untyped-def]
    connection = _legacy_v2_connection(tmp_path / "idempotent.sqlite3")
    MigrationManager(connection).migrate()
    MigrationManager(connection).migrate()
    count = connection.execute(
        "SELECT COUNT(*) FROM schema_migrations WHERE version = 3"
    ).fetchone()[0]
    connection.close()

    assert count == 1
