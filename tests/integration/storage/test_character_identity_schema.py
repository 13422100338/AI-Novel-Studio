import sqlite3

import pytest

from ai_novel_studio.infrastructure.storage.migration_manager import LATEST_SCHEMA_VERSION
from ai_novel_studio.infrastructure.storage.project_repository import ProjectRepository


def test_schema_v11_adds_character_identity_merge_and_review_tables(tmp_path) -> None:  # type: ignore[no-untyped-def]
    project = ProjectRepository.create(tmp_path / "project", "Identity Merge Test")

    with project.database.connect() as connection:
        version = int(connection.execute("PRAGMA user_version").fetchone()[0])
        columns = {
            str(row[1])
            for row in connection.execute(
                "PRAGMA table_info(character_identity_merges)"
            ).fetchall()
        }
        indexes = {
            str(row[1])
            for row in connection.execute(
                "PRAGMA index_list(character_identity_merges)"
            ).fetchall()
        }
        decision_columns = {
            str(row[1])
            for row in connection.execute(
                "PRAGMA table_info(character_identity_review_decisions)"
            ).fetchall()
        }
        view_move_columns = {
            str(row[1])
            for row in connection.execute(
                "PRAGMA table_info(character_identity_merge_view_assertions)"
            ).fetchall()
        }

    assert version == LATEST_SCHEMA_VERSION == 14
    assert {
        "id",
        "source_character_id",
        "target_character_id",
        "source_canonical_name",
        "source_aliases_json",
        "target_aliases_before_json",
        "target_aliases_after_json",
        "moved_state_event_ids_json",
        "moved_knowledge_event_ids_json",
        "moved_briefs_json",
        "reason",
        "status",
        "created_at",
        "reversed_at",
    } <= columns
    assert "character_identity_one_active_source" in indexes
    assert {
        "first_character_id",
        "second_character_id",
        "decision",
        "reason",
        "created_at",
        "updated_at",
    } == decision_columns
    assert {"merge_id", "assertion_id", "reference_role"} == view_move_columns


def test_schema_v10_rejects_self_merge(tmp_path) -> None:  # type: ignore[no-untyped-def]
    project = ProjectRepository.create(tmp_path / "project", "Identity Constraint Test")
    with project.database.connect() as connection, connection:
        connection.execute(
            "INSERT INTO characters VALUES (?, ?, ?, ?, ?, ?)",
            ("character-1", "Alice", "[]", "", "2026-07-16", "2026-07-16"),
        )
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute(
                "INSERT INTO character_identity_merges VALUES "
                "(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    "merge-1",
                    "character-1",
                    "character-1",
                    "Alice",
                    "[]",
                    "[]",
                    "[]",
                    "[]",
                    "[]",
                    "[]",
                    "",
                    "APPLIED",
                    "2026-07-16",
                    None,
                ),
            )


def test_schema_v10_rejects_empty_merge_reason(tmp_path) -> None:  # type: ignore[no-untyped-def]
    project = ProjectRepository.create(tmp_path / "project", "Identity Reason Test")
    with project.database.connect() as connection, connection:
        connection.executemany(
            "INSERT INTO characters VALUES (?, ?, ?, ?, ?, ?)",
            (
                ("character-1", "Alice", "[]", "", "2026-07-16", "2026-07-16"),
                ("character-2", "Alice Smith", "[]", "", "2026-07-16", "2026-07-16"),
            ),
        )
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute(
                "INSERT INTO character_identity_merges VALUES "
                "(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    "merge-1",
                    "character-1",
                    "character-2",
                    "Alice",
                    "[]",
                    "[]",
                    "[]",
                    "[]",
                    "[]",
                    "[]",
                    "   ",
                    "APPLIED",
                    "2026-07-16",
                    None,
                ),
            )
