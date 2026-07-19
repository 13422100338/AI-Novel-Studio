import json
import sqlite3

import pytest

from ai_novel_studio.infrastructure.storage.character_memory_repository import (
    CharacterMemoryRepository,
)
from ai_novel_studio.infrastructure.storage.migration_manager import (
    LATEST_SCHEMA_VERSION,
    MIGRATIONS,
    MigrationManager,
)
from ai_novel_studio.infrastructure.storage.project_repository import ProjectRepository
from ai_novel_studio.infrastructure.storage.subject_repository import SubjectRepository


def test_schema_v12_backfills_character_subjects_and_aliases(tmp_path) -> None:  # type: ignore[no-untyped-def]
    database_path = tmp_path / "legacy-v11.sqlite3"
    connection = sqlite3.connect(database_path)
    connection.row_factory = sqlite3.Row
    with connection:
        connection.execute(
            "CREATE TABLE schema_migrations (version INTEGER PRIMARY KEY, applied_at TEXT)"
        )
        for version in range(1, 12):
            MIGRATIONS[version](connection)
            connection.execute(
                "INSERT INTO schema_migrations(version, applied_at) VALUES (?, ?)",
                (version, "2026-07-18T00:00:00+00:00"),
            )
        connection.execute("PRAGMA user_version = 11")
        connection.executemany(
            "INSERT INTO characters VALUES (?, ?, ?, ?, ?, ?)",
            (
                (
                    "character-short",
                    "艾瑞克",
                    json.dumps(("艾瑞",), ensure_ascii=False),
                    "",
                    "2026-07-18T00:00:00+00:00",
                    "2026-07-18T00:00:00+00:00",
                ),
                (
                    "character-full",
                    "艾瑞克·温德米尔",
                    json.dumps(("温德米尔", "艾瑞克", "艾瑞"), ensure_ascii=False),
                    "",
                    "2026-07-18T00:00:00+00:00",
                    "2026-07-18T00:00:00+00:00",
                ),
            ),
        )
        connection.execute(
            """
            INSERT INTO character_identity_merges VALUES (
                ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'APPLIED', ?, NULL
            )
            """,
            (
                "merge-1",
                "character-short",
                "character-full",
                "艾瑞克",
                json.dumps(("艾瑞",), ensure_ascii=False),
                json.dumps(("温德米尔",), ensure_ascii=False),
                json.dumps(("温德米尔", "艾瑞克", "艾瑞"), ensure_ascii=False),
                "[]",
                "[]",
                "[]",
                "用户确认简称与全称属于同一人物",
                "2026-07-18T00:00:00+00:00",
            ),
        )

    MigrationManager(connection).migrate()

    version = int(connection.execute("PRAGMA user_version").fetchone()[0])
    subjects = connection.execute(
        "SELECT id, type, canonical_name, active FROM subjects ORDER BY id"
    ).fetchall()
    aliases = connection.execute(
        "SELECT subject_id, alias, source_id, confirmed "
        "FROM subject_aliases ORDER BY subject_id, alias"
    ).fetchall()
    connection.close()

    assert version == LATEST_SCHEMA_VERSION == 16
    assert [tuple(row) for row in subjects] == [
        ("character-full", "CHARACTER", "艾瑞克·温德米尔", 1),
        ("character-short", "CHARACTER", "艾瑞克", 0),
    ]
    assert ("character-short", "艾瑞", "character-short", 1) in {
        tuple(row) for row in aliases
    }
    assert ("character-full", "艾瑞克", "character-short", 1) in {
        tuple(row) for row in aliases
    }


def test_character_creation_registers_one_stable_subject_and_confirmed_aliases(
    tmp_path,
) -> None:  # type: ignore[no-untyped-def]
    project = ProjectRepository.create(tmp_path / "project", "Subject Registry Test")
    character = CharacterMemoryRepository(project).create_character(
        "艾瑞克·温德米尔",
        ("艾瑞克", "艾瑞克·温德米尔", "三少爷", "艾瑞克"),
    )
    subjects = SubjectRepository(project)

    subject = subjects.get(character.id)
    aliases = subjects.list_aliases(character.id)

    assert subject.id == character.id
    assert subject.type.value == "CHARACTER"
    assert subject.canonical_name == "艾瑞克·温德米尔"
    assert subject.active is True
    assert [(item.alias, item.source_id, item.confirmed) for item in aliases] == [
        ("三少爷", character.id, True),
        ("艾瑞克", character.id, True),
    ]
    assert [item.id for item in subjects.resolve_character_name("艾瑞克")] == [
        character.id
    ]


def test_schema_v12_rejects_invalid_alias_payload_without_partial_migration(
    tmp_path,
) -> None:  # type: ignore[no-untyped-def]
    connection = sqlite3.connect(tmp_path / "invalid-aliases.sqlite3")
    connection.row_factory = sqlite3.Row
    with connection:
        connection.execute(
            "CREATE TABLE schema_migrations (version INTEGER PRIMARY KEY, applied_at TEXT)"
        )
        for version in range(1, 12):
            MIGRATIONS[version](connection)
            connection.execute(
                "INSERT INTO schema_migrations(version, applied_at) VALUES (?, ?)",
                (version, "2026-07-18T00:00:00+00:00"),
            )
        connection.execute("PRAGMA user_version = 11")
        connection.execute(
            "INSERT INTO characters VALUES (?, ?, ?, ?, ?, ?)",
            (
                "character-invalid",
                "错误别名人物",
                '{"not":"a string list"}',
                "",
                "2026-07-18T00:00:00+00:00",
                "2026-07-18T00:00:00+00:00",
            ),
        )

    with pytest.raises(ValueError, match="JSON string list"):
        MigrationManager(connection).migrate()

    version = int(connection.execute("PRAGMA user_version").fetchone()[0])
    tables = {
        str(row[0])
        for row in connection.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table'"
        ).fetchall()
    }
    connection.close()

    assert version == 11
    assert "subjects" not in tables
    assert "subject_aliases" not in tables


def test_legacy_character_identity_mirror_cannot_override_subject_registry(
    tmp_path,
) -> None:  # type: ignore[no-untyped-def]
    project = ProjectRepository.create(tmp_path / "project", "Identity Source Test")
    memory = CharacterMemoryRepository(project)
    character = memory.create_character("艾瑞克·温德米尔", ("艾瑞克",))
    with project.database.connect() as connection, connection:
        connection.execute(
            "UPDATE characters SET canonical_name = ?, aliases_json = ? WHERE id = ?",
            ("被篡改的旧名称", '["被篡改的旧别名"]', character.id),
        )

    loaded = memory.get_character(character.id)
    listed = memory.list_characters()

    assert loaded.canonical_name == "艾瑞克·温德米尔"
    assert loaded.aliases == ("艾瑞克",)
    assert listed == (loaded,)
