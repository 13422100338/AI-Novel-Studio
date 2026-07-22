import sqlite3
from collections.abc import Callable
from pathlib import Path

import pytest

import ai_novel_studio.infrastructure.storage.migration_manager as migration_module
from ai_novel_studio.domain.memory import MemoryStatus, ReviewStatus
from ai_novel_studio.infrastructure.storage.project_repository import ProjectRepository
from ai_novel_studio.infrastructure.storage.schema_migrations import (
    _compose_migrations,
)
from ai_novel_studio.infrastructure.storage.search_repository import SearchRepository


def _noop_migration(connection: sqlite3.Connection) -> None:
    del connection


def _index_document(project: ProjectRepository):  # type: ignore[no-untyped-def]
    return SearchRepository(project).index_document(
        document_type="CANON",
        source_id="canon-embedding-source",
        chapter_id=None,
        title="继承权记录",
        content="公爵曾经私下指定继承人。",
        participants=(),
        pinned_weight=0,
        review_status=ReviewStatus.APPROVED,
        status=MemoryStatus.CURRENT,
    )


def _insert_v15_memory_document(project: ProjectRepository) -> str:
    document_id = "legacy-memory-document"
    with project.database.connect() as connection, connection:
        connection.execute(
            """
            INSERT INTO memory_documents (
                id, document_type, source_id, chapter_id, volume_id,
                source_revision, source_hash, title, content, participants,
                pinned_weight, review_status, status, updated_at
            ) VALUES (?, 'CANON', 'legacy-canon-source', NULL, NULL, 0, '',
                      '继承权记录', '公爵曾经私下指定继承人。', '', 0,
                      'APPROVED', 'CURRENT', '2026-07-19')
            """,
            (document_id,),
        )
    return document_id


def test_schema_v16_adds_constrained_embedding_cache(tmp_path: Path) -> None:
    project = ProjectRepository.create(tmp_path / "project", "Embedding schema")
    document = _index_document(project)

    with project.database.connect() as connection, connection:
        version = int(connection.execute("PRAGMA user_version").fetchone()[0])
        columns = {
            str(row[1])
            for row in connection.execute(
                "PRAGMA table_info(memory_embeddings)"
            ).fetchall()
        }
        indexes = {
            str(row[1])
            for row in connection.execute(
                "PRAGMA index_list(memory_embeddings)"
            ).fetchall()
        }
        connection.execute(
            """
            INSERT INTO memory_embeddings VALUES (
                ?, 'embedding-model', 3, '[0.1,0.2,0.3]', ?, 'CURRENT',
                '2026-07-19T00:00:00+00:00', '2026-07-19T00:00:00+00:00'
            )
            """,
            (document.id, "a" * 64),
        )
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute(
                """
                INSERT INTO memory_embeddings VALUES (
                    ?, 'invalid-dimension', 0, '[]', ?, 'CURRENT',
                    '2026-07-19', '2026-07-19'
                )
                """,
                (document.id, "b" * 64),
            )
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute(
                """
                INSERT INTO memory_embeddings VALUES (
                    ?, 'invalid-status', 2, '[0.1,0.2]', ?, 'REVIEW',
                    '2026-07-19', '2026-07-19'
                )
                """,
                (document.id, "c" * 64),
            )
        connection.execute("DELETE FROM memory_documents WHERE id = ?", (document.id,))
        remaining = int(
            connection.execute(
                "SELECT COUNT(*) FROM memory_embeddings WHERE document_id = ?",
                (document.id,),
            ).fetchone()[0]
        )

    assert version == migration_module.LATEST_SCHEMA_VERSION == 17
    assert columns == {
        "document_id",
        "model_id",
        "dimensions",
        "vector_json",
        "content_hash",
        "status",
        "created_at",
        "updated_at",
    }
    assert "memory_embeddings_rebuild" in indexes
    assert remaining == 0


def test_migration_registry_rejects_duplicate_or_missing_versions() -> None:
    migration: Callable[[sqlite3.Connection], None] = _noop_migration

    with pytest.raises(RuntimeError, match="invalid schema migration"):
        _compose_migrations({0: migration, 1: migration})
    with pytest.raises(RuntimeError, match="duplicate schema migration"):
        _compose_migrations({1: migration}, {1: migration})
    with pytest.raises(RuntimeError, match="missing schema migration"):
        _compose_migrations({1: migration}, {3: migration})


def test_failed_v16_migration_rolls_back_and_retries_without_data_loss(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "legacy-v15"
    real_migration = migration_module.MIGRATIONS[16]
    monkeypatch.setattr(migration_module, "LATEST_SCHEMA_VERSION", 15)
    legacy = ProjectRepository.create(root, "Legacy v15")
    document_id = _insert_v15_memory_document(legacy)

    monkeypatch.setattr(migration_module, "LATEST_SCHEMA_VERSION", 16)

    def fail_during_migration(connection: sqlite3.Connection) -> None:
        connection.execute(
            "CREATE TABLE memory_embeddings (document_id TEXT PRIMARY KEY)"
        )
        raise RuntimeError("injected v16 migration interruption")

    monkeypatch.setitem(migration_module.MIGRATIONS, 16, fail_during_migration)

    with pytest.raises(RuntimeError, match="injected v16 migration interruption"):
        ProjectRepository.open(root)

    with sqlite3.connect(root / "project.sqlite3") as connection:
        version_after_failure = int(
            connection.execute("PRAGMA user_version").fetchone()[0]
        )
        tables_after_failure = {
            str(row[0])
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            ).fetchall()
        }
        preserved = connection.execute(
            "SELECT title, content FROM memory_documents WHERE id = ?",
            (document_id,),
        ).fetchone()

    assert version_after_failure == 15
    assert "memory_embeddings" not in tables_after_failure
    assert tuple(preserved) == ("继承权记录", "公爵曾经私下指定继承人。")

    monkeypatch.setitem(migration_module.MIGRATIONS, 16, real_migration)
    recovered = ProjectRepository.open(root)

    with recovered.database.connect() as connection:
        recovered_version = int(connection.execute("PRAGMA user_version").fetchone()[0])
        migration_16_count = int(
            connection.execute(
                "SELECT COUNT(*) FROM schema_migrations WHERE version = 16"
            ).fetchone()[0]
        )
        recovered_document = connection.execute(
            "SELECT title, content FROM memory_documents WHERE id = ?",
            (document_id,),
        ).fetchone()

    assert recovered_version == 16
    assert migration_16_count == 1
    assert tuple(recovered_document) == ("继承权记录", "公爵曾经私下指定继承人。")
