import sqlite3

import pytest

import ai_novel_studio.infrastructure.storage.migration_manager as migration_module
from ai_novel_studio.domain.audit import AuditRunStatus, AuditTargetKind
from ai_novel_studio.domain.generation import AuditPolicy, CreationMode, GenerationProfile
from ai_novel_studio.infrastructure.storage.audit_repository import AuditRepository
from ai_novel_studio.infrastructure.storage.chapter_repository import ChapterRepository
from ai_novel_studio.infrastructure.storage.generation_repository import GenerationRepository
from ai_novel_studio.infrastructure.storage.migration_manager import (
    LATEST_SCHEMA_VERSION,
    MigrationManager,
    _migration_1,
    _migration_2,
)
from ai_novel_studio.infrastructure.storage.project_repository import ProjectRepository


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
        title, category = connection.execute(
            "SELECT title, category FROM canon_entries WHERE id = 'canon-1'"
        ).fetchone()
        version = connection.execute("PRAGMA user_version").fetchone()[0]
    finally:
        connection.close()

    assert version == LATEST_SCHEMA_VERSION == 17
    assert title == "旧港状态"
    assert category is None
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


def test_v17_preserves_legacy_rows_and_round_trips_new_audit_policies(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:  # type: ignore[no-untyped-def]
    root = tmp_path / "legacy-v16"
    monkeypatch.setattr(migration_module, "LATEST_SCHEMA_VERSION", 16)
    legacy = ProjectRepository.create(root, "Legacy v16")
    legacy_chapter = ChapterRepository(legacy).create_chapter(
        legacy.list_volumes()[0].id, "Legacy", "1", "old text"
    )
    with legacy.database.connect() as connection, connection:
        connection.execute(
            """
            INSERT INTO generation_runs(
                id, chapter_id, mode, status, model_provider_id, model_id,
                output_token_limit, prompt_version, started_at, updated_at
            ) VALUES (?, ?, 'STRICT', 'FAILED', 'provider', 'model', 8000,
                      'prose-v1', '2026-07-22T00:00:00+00:00', '2026-07-22T00:00:00+00:00')
            """,
            ("legacy-generation", legacy_chapter.id),
        )
        connection.execute(
            """
            INSERT INTO audit_runs(
                id, chapter_id, target_kind, target_id, target_revision, target_hash,
                mode, status, prompt_version, started_at
            ) VALUES (?, ?, 'GENERATED_DRAFT', 'legacy-generation', 0, 'hash',
                      'STRICT', 'COMPLETED', 'audit-v1', '2026-07-22T00:00:00+00:00')
            """,
            ("legacy-audit", legacy_chapter.id),
        )

    monkeypatch.setattr(migration_module, "LATEST_SCHEMA_VERSION", 17)
    migrated = ProjectRepository.open(root)
    generations = GenerationRepository(migrated)
    audits = AuditRepository(migrated)
    legacy_generation = generations.get("legacy-generation")
    legacy_audit = audits.get_run("legacy-audit")

    assert legacy_generation.mode == CreationMode.STRICT
    assert legacy_generation.generation_profile == GenerationProfile.NORMAL
    assert legacy_generation.audit_policy == AuditPolicy.STANDARD
    assert legacy_audit.mode == CreationMode.STRICT
    assert legacy_audit.generation_profile == GenerationProfile.NORMAL
    assert legacy_audit.audit_policy == AuditPolicy.STANDARD
    with migrated.database.connect() as connection:
        legacy_generation_policy = connection.execute(
            "SELECT audit_policy FROM generation_runs WHERE id = 'legacy-generation'"
        ).fetchone()[0]
        legacy_audit_policy = connection.execute(
            "SELECT audit_policy FROM audit_runs WHERE id = 'legacy-audit'"
        ).fetchone()[0]
    assert legacy_generation_policy is None
    assert legacy_audit_policy is None

    new_chapter = ChapterRepository(migrated).create_chapter(
        migrated.list_volumes()[0].id, "New", "2", "new text"
    )
    new_generation = generations.create_preparing(
        chapter_id=new_chapter.id,
        mode=CreationMode.STANDARD,
        brief_id=None,
        brief_revision=None,
        model_provider_id="provider",
        model_id="model",
        output_token_limit=8000,
        prompt_version="prose-v1",
        audit_policy=AuditPolicy.DEEP,
    )
    new_audit = audits.create_run(
        chapter_id=new_chapter.id,
        target_kind=AuditTargetKind.FORMAL_CHAPTER,
        target_id=new_chapter.id,
        target_revision=0,
        target_hash="hash",
        mode=CreationMode.STANDARD,
        status=AuditRunStatus.PREPARING,
        prompt_version="audit-v1",
        audit_policy=AuditPolicy.STANDARD,
    )

    assert new_generation.audit_policy == AuditPolicy.DEEP
    assert new_audit.audit_policy == AuditPolicy.STANDARD
    with migrated.database.connect() as connection:
        stored_generation = connection.execute(
            "SELECT audit_policy FROM generation_runs WHERE id = ?", (new_generation.id,)
        ).fetchone()[0]
        stored_audit = connection.execute(
            "SELECT audit_policy FROM audit_runs WHERE id = ?", (new_audit.id,)
        ).fetchone()[0]
    assert stored_generation == AuditPolicy.DEEP.value
    assert stored_audit == AuditPolicy.STANDARD.value

    reopened = ProjectRepository.open(root)
    reopened_generation = GenerationRepository(reopened).get(new_generation.id)
    reopened_audit = AuditRepository(reopened).get_run(new_audit.id)
    assert reopened_generation.audit_policy == AuditPolicy.DEEP
    assert reopened_audit.audit_policy == AuditPolicy.STANDARD


def test_v17_rolls_back_column_additions_and_can_retry(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:  # type: ignore[no-untyped-def]
    root = tmp_path / "interrupted-v17"
    monkeypatch.setattr(migration_module, "LATEST_SCHEMA_VERSION", 16)
    ProjectRepository.create(root, "Legacy v16")
    monkeypatch.setattr(migration_module, "LATEST_SCHEMA_VERSION", 17)
    real_migration = migration_module.MIGRATIONS[17]

    def fail_after_generation_column(connection: sqlite3.Connection) -> None:
        connection.execute("ALTER TABLE generation_runs ADD COLUMN audit_policy TEXT")
        raise RuntimeError("injected v17 migration interruption")

    monkeypatch.setitem(migration_module.MIGRATIONS, 17, fail_after_generation_column)
    with pytest.raises(RuntimeError, match="injected v17 migration interruption"):
        ProjectRepository.open(root)

    with sqlite3.connect(root / "project.sqlite3") as connection:
        version = int(connection.execute("PRAGMA user_version").fetchone()[0])
        generation_columns = {
            str(row[1]) for row in connection.execute("PRAGMA table_info(generation_runs)")
        }
        audit_columns = {
            str(row[1]) for row in connection.execute("PRAGMA table_info(audit_runs)")
        }
    assert version == 16
    assert "audit_policy" not in generation_columns
    assert "audit_policy" not in audit_columns

    monkeypatch.setitem(migration_module.MIGRATIONS, 17, real_migration)
    reopened = ProjectRepository.open(root)
    with reopened.database.connect() as connection:
        version = int(connection.execute("PRAGMA user_version").fetchone()[0])
    assert version == 17


def test_v17_rejects_invalid_audit_policy_values(tmp_path) -> None:  # type: ignore[no-untyped-def]
    project = ProjectRepository.create(tmp_path / "policy-constraints", "Policy constraints")
    chapter = ChapterRepository(project).create_chapter(
        project.list_volumes()[0].id, "Chapter", "1", "text"
    )
    generation = GenerationRepository(project).create_preparing(
        chapter_id=chapter.id,
        mode=CreationMode.BASIC,
        brief_id=None,
        brief_revision=None,
        model_provider_id="provider",
        model_id="model",
        output_token_limit=8000,
        prompt_version="prose-v1",
    )
    audit = AuditRepository(project).create_run(
        chapter_id=chapter.id,
        target_kind=AuditTargetKind.FORMAL_CHAPTER,
        target_id=chapter.id,
        target_revision=0,
        target_hash="hash",
        mode=CreationMode.BASIC,
        status=AuditRunStatus.PREPARING,
        prompt_version="audit-v1",
    )

    with project.database.connect() as connection, pytest.raises(sqlite3.IntegrityError):
        connection.execute(
            "UPDATE generation_runs SET audit_policy = 'INVALID' WHERE id = ?",
            (generation.id,),
        )
    with project.database.connect() as connection, pytest.raises(sqlite3.IntegrityError):
        connection.execute(
            "UPDATE audit_runs SET audit_policy = 'INVALID' WHERE id = ?",
            (audit.id,),
        )
