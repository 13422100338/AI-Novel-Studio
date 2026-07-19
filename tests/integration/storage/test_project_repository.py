import json
import sqlite3
from pathlib import Path

import pytest

from ai_novel_studio.domain.character_identity import CharacterIdentityReviewDecisionType
from ai_novel_studio.infrastructure.storage.character_identity_repository import (
    CharacterIdentityRepository,
)
from ai_novel_studio.infrastructure.storage.migration_manager import (
    LATEST_SCHEMA_VERSION,
    MIGRATIONS,
    MigrationManager,
)
from ai_novel_studio.infrastructure.storage.project_repository import ProjectRepository


def _create_legacy_v7_project(root: Path) -> tuple[str, str]:
    project_id = "00000000-0000-0000-0000-000000000001"
    volume_id = "00000000-0000-0000-0000-000000000002"
    chapter_id = "00000000-0000-0000-0000-000000000003"
    short_character_id = "00000000-0000-0000-0000-000000000004"
    full_character_id = "00000000-0000-0000-0000-000000000005"
    canon_id = "00000000-0000-0000-0000-000000000006"
    timestamp = "2026-07-14T00:00:00+00:00"
    root.mkdir()
    (root / "manuscript").mkdir()
    (root / "manuscript" / "chapter-1.md").write_text(
        "旧项目正文不会被迁移改写。\n", encoding="utf-8"
    )
    (root / "project.json").write_text(
        json.dumps(
            {"format_version": 1, "project_id": project_id, "title": "旧项目"},
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    with sqlite3.connect(root / "project.sqlite3") as connection:
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute(
            "CREATE TABLE schema_migrations (version INTEGER PRIMARY KEY, "
            "applied_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)"
        )
        for version in range(1, 8):
            MIGRATIONS[version](connection)
            connection.execute(
                "INSERT INTO schema_migrations(version, applied_at) VALUES (?, ?)",
                (version, timestamp),
            )
        connection.execute("PRAGMA user_version = 7")
        connection.execute(
            "INSERT INTO projects VALUES (?, ?, ?, ?, ?)",
            (project_id, "旧项目", 1, timestamp, timestamp),
        )
        connection.execute(
            "INSERT INTO volumes VALUES (?, ?, ?, ?, ?, ?)",
            (volume_id, "旧卷", "保留的卷简介", 0, timestamp, timestamp),
        )
        connection.execute(
            "INSERT INTO chapters VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                chapter_id,
                volume_id,
                "1",
                "旧章",
                "保留的章节简介",
                "manuscript/chapter-1.md",
                "legacy-chapter-hash",
                0,
                3,
                "ready",
                0,
                None,
                timestamp,
                timestamp,
            ),
        )
        connection.executemany(
            "INSERT INTO characters VALUES (?, ?, ?, ?, ?, ?)",
            (
                (
                    short_character_id,
                    "艾瑞克",
                    "[]",
                    "保留的简称人物卡",
                    timestamp,
                    timestamp,
                ),
                (
                    full_character_id,
                    "艾瑞克·温德米尔",
                    '["温德米尔"]',
                    "保留的全称人物卡",
                    timestamp,
                    timestamp,
                ),
            ),
        )
        connection.execute(
            "INSERT INTO canon_entries VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                canon_id,
                "旧港状态",
                "旧港已经封闭",
                chapter_id,
                None,
                1.0,
                "USER_CONFIRMED",
                "CURRENT",
                "LOCKED",
                timestamp,
                timestamp,
            ),
        )
    return short_character_id, full_character_id


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

    assert version == LATEST_SCHEMA_VERSION
    assert [row[0] for row in rows] == list(range(1, LATEST_SCHEMA_VERSION + 1))


def test_open_restores_project_identity_and_structure(tmp_path: Path) -> None:
    root = tmp_path / "novel"
    created = ProjectRepository.create(root, "My Novel")

    reopened = ProjectRepository.open(root)

    assert reopened.project.id == created.project.id
    assert reopened.project.title == "My Novel"
    assert reopened.list_volumes() == created.list_volumes()


def test_open_migrates_v7_project_and_reopens_v11_review_state(tmp_path: Path) -> None:
    root = tmp_path / "legacy-v7"
    short_character_id, full_character_id = _create_legacy_v7_project(root)

    migrated = ProjectRepository.open(root)

    with migrated.database.connect() as connection:
        version = int(connection.execute("PRAGMA user_version").fetchone()[0])
        migration_versions = [
            int(row[0])
            for row in connection.execute(
                "SELECT version FROM schema_migrations ORDER BY version"
            ).fetchall()
        ]
        chapter = connection.execute(
            "SELECT title, synopsis, revision, memory_status FROM chapters"
        ).fetchone()
        canon = connection.execute(
            "SELECT title, detail, category FROM canon_entries"
        ).fetchone()
        tables = {
            str(row[0])
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            ).fetchall()
        }

    assert version == LATEST_SCHEMA_VERSION == 16
    assert migration_versions == list(range(1, LATEST_SCHEMA_VERSION + 1))
    assert migrated.project.title == "旧项目"
    assert migrated.list_volumes()[0].title == "旧卷"
    assert tuple(chapter) == ("旧章", "保留的章节简介", 3, "ready")
    assert tuple(canon) == ("旧港状态", "旧港已经封闭", None)
    assert {
        "project_guidance",
        "character_identity_merges",
        "character_identity_review_decisions",
        "subjects",
        "subject_aliases",
        "view_assertions",
        "character_identity_merge_view_assertions",
    } <= tables
    assert (root / "manuscript" / "chapter-1.md").read_text(encoding="utf-8") == (
        "旧项目正文不会被迁移改写。\n"
    )

    saved = CharacterIdentityRepository(migrated).set_review_decision(
        short_character_id,
        full_character_id,
        CharacterIdentityReviewDecisionType.DISTINCT,
        reason="用户确认简称人物卡并非同一人物",
    )
    reopened = ProjectRepository.open(root)
    restored = CharacterIdentityRepository(reopened).get_review_decision(
        short_character_id,
        full_character_id,
    )

    assert restored == saved
    assert reopened.project == migrated.project
    assert reopened.list_volumes() == migrated.list_volumes()


def test_failed_v7_migration_rolls_back_and_can_retry(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "interrupted-v7"
    _create_legacy_v7_project(root)
    real_migration_10 = MIGRATIONS[10]

    def fail_during_migration_10(connection: sqlite3.Connection) -> None:
        connection.execute("CREATE TABLE interrupted_migration (id TEXT PRIMARY KEY)")
        raise RuntimeError("injected migration interruption")

    monkeypatch.setitem(MIGRATIONS, 10, fail_during_migration_10)

    with pytest.raises(RuntimeError, match="injected migration interruption"):
        ProjectRepository.open(root)

    with sqlite3.connect(root / "project.sqlite3") as connection:
        version_after_failure = int(
            connection.execute("PRAGMA user_version").fetchone()[0]
        )
        migration_versions_after_failure = [
            int(row[0])
            for row in connection.execute(
                "SELECT version FROM schema_migrations ORDER BY version"
            ).fetchall()
        ]
        tables_after_failure = {
            str(row[0])
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            ).fetchall()
        }
        canon_columns_after_failure = {
            str(row[1])
            for row in connection.execute("PRAGMA table_info(canon_entries)").fetchall()
        }
        chapter_after_failure = connection.execute(
            "SELECT title, synopsis, revision, memory_status FROM chapters"
        ).fetchone()

    assert version_after_failure == 7
    assert migration_versions_after_failure == list(range(1, 8))
    assert "project_guidance" not in tables_after_failure
    assert "interrupted_migration" not in tables_after_failure
    assert "category" not in canon_columns_after_failure
    assert tuple(chapter_after_failure) == ("旧章", "保留的章节简介", 3, "ready")
    assert (root / "manuscript" / "chapter-1.md").read_text(encoding="utf-8") == (
        "旧项目正文不会被迁移改写。\n"
    )

    monkeypatch.setitem(MIGRATIONS, 10, real_migration_10)
    recovered = ProjectRepository.open(root)

    with recovered.database.connect() as connection:
        recovered_version = int(connection.execute("PRAGMA user_version").fetchone()[0])
        recovered_migration_versions = [
            int(row[0])
            for row in connection.execute(
                "SELECT version FROM schema_migrations ORDER BY version"
            ).fetchall()
        ]
        recovered_tables = {
            str(row[0])
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            ).fetchall()
        }

    assert recovered_version == LATEST_SCHEMA_VERSION == 16
    assert recovered_migration_versions == list(range(1, LATEST_SCHEMA_VERSION + 1))
    assert "project_guidance" in recovered_tables
    assert "character_identity_review_decisions" in recovered_tables
    assert "subjects" in recovered_tables
    assert "subject_aliases" in recovered_tables
    assert "view_assertions" in recovered_tables
    assert "character_identity_merge_view_assertions" in recovered_tables
    assert "interrupted_migration" not in recovered_tables
    assert recovered.project.title == "旧项目"
    assert recovered.list_volumes()[0].title == "旧卷"


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
