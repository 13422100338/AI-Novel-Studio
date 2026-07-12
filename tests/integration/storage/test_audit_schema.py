import sqlite3

import pytest

from ai_novel_studio.infrastructure.storage.migration_manager import (
    LATEST_SCHEMA_VERSION,
    MigrationManager,
    _migration_1,
    _migration_2,
    _migration_3,
)


def _legacy_v3_connection(path):  # type: ignore[no-untyped-def]
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
        _migration_3(connection)
        connection.execute("PRAGMA user_version = 3")
        connection.executemany(
            "INSERT INTO schema_migrations(version, applied_at) VALUES (?, ?)",
            ((1, "2026-07-03"), (2, "2026-07-03"), (3, "2026-07-03")),
        )
        connection.execute(
            "INSERT INTO projects VALUES (?, ?, ?, ?, ?)",
            ("project-1", "Legacy Project", 1, "2026-07-03", "2026-07-03"),
        )
        connection.execute(
            "INSERT INTO volumes VALUES (?, ?, ?, ?, ?, ?)",
            ("volume-1", "Volume One", "", 0, "2026-07-03", "2026-07-03"),
        )
        connection.execute(
            "INSERT INTO chapters VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                "chapter-1",
                "volume-1",
                "1",
                "Old Chapter",
                "",
                "manuscript/chapter-1.md",
                "chapter-hash",
                0,
                3,
                "pending",
                0,
                None,
                "2026-07-03",
                "2026-07-03",
            ),
        )
        connection.execute(
            "INSERT INTO generation_runs "
            "(id, chapter_id, mode, status, model_provider_id, model_id, output_token_limit, "
            "prompt_version, started_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                "generation-run-1",
                "chapter-1",
                "BASIC",
                "COMPLETED",
                "provider",
                "model",
                3000,
                "prose-v1",
                "2026-07-03",
                "2026-07-03",
            ),
        )
    return connection


def test_schema_v4_adds_audit_tables_and_preserves_v3_data(tmp_path) -> None:  # type: ignore[no-untyped-def]
    connection = _legacy_v3_connection(tmp_path / "legacy-v3.sqlite3")
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
            "SELECT title FROM chapters WHERE id = 'chapter-1'"
        ).fetchone()[0]
        version = connection.execute("PRAGMA user_version").fetchone()[0]
    finally:
        connection.close()

    assert version == LATEST_SCHEMA_VERSION == 6
    assert title == "Old Chapter"
    assert {
        "audit_runs",
        "audit_findings",
        "repair_proposals",
        "provenance_events",
    } <= tables
    assert "audit_runs_chapter" in indexes
    assert "audit_findings_run_status" in indexes
    assert "repair_proposals_finding" in indexes
    assert "provenance_events_chapter" in indexes


def test_schema_v4_enforces_audit_status_confidence_and_revision_constraints(tmp_path) -> None:  # type: ignore[no-untyped-def]
    connection = _legacy_v3_connection(tmp_path / "constraints.sqlite3")
    MigrationManager(connection).migrate()
    with pytest.raises(sqlite3.IntegrityError):
        with connection:
            connection.execute(
                "INSERT INTO audit_runs "
                "(id, chapter_id, target_kind, target_id, target_revision, target_hash, "
                "mode, status, prompt_version, started_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    "audit-run-bad-status",
                    "chapter-1",
                    "FORMAL_CHAPTER",
                    "chapter-1",
                    3,
                    "hash",
                    "BASIC",
                    "UNKNOWN",
                    "audit-v1",
                    "2026-07-09",
                ),
            )
    with pytest.raises(sqlite3.IntegrityError):
        with connection:
            connection.execute(
                "INSERT INTO audit_runs "
                "(id, chapter_id, target_kind, target_id, target_revision, target_hash, "
                "mode, status, prompt_version, started_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    "audit-run-negative-revision",
                    "chapter-1",
                    "FORMAL_CHAPTER",
                    "chapter-1",
                    -1,
                    "hash",
                    "BASIC",
                    "PREPARING",
                    "audit-v1",
                    "2026-07-09",
                ),
            )
    with connection:
        connection.execute(
            "INSERT INTO audit_runs "
            "(id, chapter_id, target_kind, target_id, target_revision, target_hash, "
            "mode, status, prompt_version, started_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                "audit-run-1",
                "chapter-1",
                "FORMAL_CHAPTER",
                "chapter-1",
                3,
                "hash",
                "BASIC",
                "RULE_CHECKED",
                "audit-v1",
                "2026-07-09",
            ),
        )
    with pytest.raises(sqlite3.IntegrityError):
        with connection:
            connection.execute(
                "INSERT INTO audit_findings "
                "(id, run_id, category, severity, source, location_json, evidence, "
                "explanation, related_source_json, confidence, status, created_at, updated_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    "finding-bad-confidence",
                    "audit-run-1",
                    "STYLE",
                    "INFO",
                    "MODEL",
                    "{}",
                    "evidence",
                    "explanation",
                    "[]",
                    1.1,
                    "OPEN",
                    "2026-07-09",
                    "2026-07-09",
                ),
            )
    connection.close()


def test_schema_v4_migration_is_idempotent(tmp_path) -> None:  # type: ignore[no-untyped-def]
    connection = _legacy_v3_connection(tmp_path / "idempotent.sqlite3")
    MigrationManager(connection).migrate()
    MigrationManager(connection).migrate()
    count = connection.execute(
        "SELECT COUNT(*) FROM schema_migrations WHERE version = 4"
    ).fetchone()[0]
    connection.close()

    assert count == 1
