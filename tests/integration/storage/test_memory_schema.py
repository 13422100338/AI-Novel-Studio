import sqlite3

from ai_novel_studio.infrastructure.storage.migration_manager import (
    LATEST_SCHEMA_VERSION,
    MigrationManager,
    _migration_1,
)
from ai_novel_studio.infrastructure.storage.project_repository import ProjectRepository

EXPECTED_TABLES = {
    "characters",
    "character_state_events",
    "knowledge_items",
    "knowledge_state_events",
    "canon_entries",
    "narrative_clues",
    "narrative_clue_events",
    "summary_nodes",
    "style_rules",
    "style_samples",
    "memory_dependencies",
    "memory_documents",
    "context_manifests",
    "chapter_context_pins",
    "project_guidance",
    "character_identity_merges",
    "memory_fts",
}


def test_schema_v2_adds_memory_tables_and_preserves_existing_chapters(tmp_path) -> None:  # type: ignore[no-untyped-def]
    database_path = tmp_path / "legacy-v1.sqlite3"
    connection = sqlite3.connect(database_path)
    connection.execute("PRAGMA foreign_keys = ON")
    with connection:
        connection.execute(
            "CREATE TABLE schema_migrations (version INTEGER PRIMARY KEY, "
            "applied_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)"
        )
        _migration_1(connection)
        connection.execute("PRAGMA user_version = 1")
        connection.execute("INSERT INTO schema_migrations VALUES (1, '2026-07-03')")
        connection.execute(
            "INSERT INTO projects VALUES (?, ?, ?, ?, ?)",
            ("project-1", "旧项目", 1, "2026-07-03", "2026-07-03"),
        )
        connection.execute(
            "INSERT INTO volumes VALUES (?, ?, ?, ?, ?, ?)",
            ("volume-1", "未分卷", "", 0, "2026-07-03", "2026-07-03"),
        )
        connection.execute(
            "INSERT INTO chapters VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                "chapter-1",
                "volume-1",
                "1",
                "旧章",
                "",
                "manuscript/chapter-1.md",
                "hash",
                0,
                0,
                "pending",
                0,
                None,
                "2026-07-03",
                "2026-07-03",
            ),
        )
    MigrationManager(connection).migrate()
    try:
        version = connection.execute("PRAGMA user_version").fetchone()[0]
        chapter_title = connection.execute(
            "SELECT title FROM chapters WHERE id = 'chapter-1'"
        ).fetchone()[0]
        tables = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type IN ('table', 'view')"
            ).fetchall()
        }
    finally:
        connection.close()

    assert chapter_title == "旧章"
    assert version == LATEST_SCHEMA_VERSION
    assert EXPECTED_TABLES <= tables


def test_memory_migration_is_idempotent_and_fts5_is_queryable(tmp_path) -> None:  # type: ignore[no-untyped-def]
    project = ProjectRepository.create(tmp_path / "project", "测试长篇")
    reopened = ProjectRepository.open(project.layout.root)
    reopened = ProjectRepository.open(reopened.layout.root)

    with reopened.database.connect() as connection, connection:
        connection.execute(
            "INSERT INTO memory_fts(document_id, title, content, participants) VALUES (?, ?, ?, ?)",
            ("doc-1", "旧港来信", "林岚在旧港发现密封来信", "林岚"),
        )
        result = connection.execute(
            "SELECT document_id FROM memory_fts WHERE memory_fts MATCH ?",
            ("旧港来",),
        ).fetchone()
        migration_count = connection.execute(
            "SELECT COUNT(*) FROM schema_migrations WHERE version = 2"
        ).fetchone()[0]

    assert result[0] == "doc-1"
    assert migration_count == 1
