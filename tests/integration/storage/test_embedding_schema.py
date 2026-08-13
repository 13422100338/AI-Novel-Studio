import sqlite3
from collections.abc import Callable
from pathlib import Path

import pytest

import ai_novel_studio.infrastructure.storage.migration_manager as migration_module
from ai_novel_studio.domain.embedding import EmbeddingIndexIdentity
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


def test_schema_v19_uses_structured_embedding_identity(tmp_path: Path) -> None:
    project = ProjectRepository.create(tmp_path / "project", "Embedding schema")
    document = _index_document(project)

    with project.database.connect() as connection, connection:
        version = int(connection.execute("PRAGMA user_version").fetchone()[0])
        table_info = connection.execute(
            "PRAGMA table_info(memory_embeddings)"
        ).fetchall()
        columns = {str(row[1]) for row in table_info}
        primary_key = [
            str(row[1])
            for row in sorted(table_info, key=lambda row: int(row[5]))
            if int(row[5]) > 0
        ]
        indexes = {
            str(row[1])
            for row in connection.execute(
                "PRAGMA index_list(memory_embeddings)"
            ).fetchall()
        }
        document_indexes = {
            str(row[1])
            for row in connection.execute(
                "PRAGMA index_list(memory_documents)"
            ).fetchall()
        }
        formal_index_columns = [
            str(row[2])
            for row in connection.execute(
                "PRAGMA index_info(memory_documents_formal_chapter_projection)"
            ).fetchall()
        ]
        connection.execute(
            """
            INSERT INTO memory_embeddings VALUES (
                ?, 'provider-a', 'embedding-model', 1, 3, '[0.1,0.2,0.3]',
                ?, 'CURRENT',
                '2026-07-19T00:00:00+00:00', '2026-07-19T00:00:00+00:00'
            )
            """,
            (document.id, "a" * 64),
        )
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute(
                """
                INSERT INTO memory_embeddings VALUES (
                    ?, 'provider-a', 'invalid-dimension', 1, 0, '[]', ?, 'CURRENT',
                    '2026-07-19', '2026-07-19'
                )
                """,
                (document.id, "b" * 64),
            )
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute(
                """
                INSERT INTO memory_embeddings VALUES (
                    ?, 'provider-a', 'invalid-status', 1, 2, '[0.1,0.2]',
                    ?, 'REVIEW',
                    '2026-07-19', '2026-07-19'
                )
                """,
                (document.id, "c" * 64),
            )
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute(
                """
                INSERT INTO memory_embeddings VALUES (
                    ?, '', 'invalid-provider', 1, 2, '[0.1,0.2]',
                    ?, 'CURRENT', '2026-07-19', '2026-07-19'
                )
                """,
                (document.id, "d" * 64),
            )
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute(
                """
                INSERT INTO memory_embeddings VALUES (
                    ?, 'provider-a', 'invalid-schema', 0, 2, '[0.1,0.2]',
                    ?, 'CURRENT', '2026-07-19', '2026-07-19'
                )
                """,
                (document.id, "e" * 64),
            )
        connection.execute("DELETE FROM memory_documents WHERE id = ?", (document.id,))
        remaining = int(
            connection.execute(
                "SELECT COUNT(*) FROM memory_embeddings WHERE document_id = ?",
                (document.id,),
            ).fetchone()[0]
        )

    assert version == migration_module.LATEST_SCHEMA_VERSION == 20
    assert columns == {
        "document_id",
        "provider_id",
        "model_id",
        "embedding_schema_version",
        "dimensions",
        "vector_json",
        "content_hash",
        "status",
        "created_at",
        "updated_at",
    }
    assert primary_key == [
        "document_id",
        "provider_id",
        "model_id",
        "embedding_schema_version",
    ]
    assert "memory_embeddings_rebuild" in indexes
    assert "memory_embeddings_recall" in indexes
    assert "memory_documents_formal_chapter_projection" in document_indexes
    assert formal_index_columns == [
        "document_type",
        "chapter_id",
        "source_revision",
        "status",
        "chunk_policy_version",
        "chunk_ordinal",
    ]
    assert remaining == 0


def test_v18_to_v19_preserves_documents_and_discards_legacy_vectors(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "legacy-v18"
    monkeypatch.setattr(migration_module, "LATEST_SCHEMA_VERSION", 18)
    legacy = ProjectRepository.create(root, "Legacy v18")
    document_id = _insert_v15_memory_document(legacy)
    with legacy.database.connect() as connection, connection:
        connection.execute(
            """
            INSERT INTO memory_embeddings VALUES (
                ?, 'embedding-model', 2, '[1.0,0.0]', ?, 'CURRENT',
                '2026-08-09T00:00:00+00:00', '2026-08-09T00:00:00+00:00'
            )
            """,
            (document_id, "a" * 64),
        )
        before_document = tuple(
            connection.execute(
                "SELECT * FROM memory_documents WHERE id = ?",
                (document_id,),
            ).fetchone()
        )

    monkeypatch.setattr(migration_module, "LATEST_SCHEMA_VERSION", 19)
    migrated = ProjectRepository.open(root)
    reopened = ProjectRepository.open(root)

    with reopened.database.connect() as connection:
        version = int(connection.execute("PRAGMA user_version").fetchone()[0])
        migration_count = int(
            connection.execute(
                "SELECT COUNT(*) FROM schema_migrations WHERE version = 19"
            ).fetchone()[0]
        )
        document = tuple(
            connection.execute(
                "SELECT * FROM memory_documents WHERE id = ?",
                (document_id,),
            ).fetchone()
        )
        embeddings = int(
            connection.execute("SELECT COUNT(*) FROM memory_embeddings").fetchone()[0]
        )

    assert migrated.project == reopened.project
    assert version == 19
    assert migration_count == 1
    assert document[:14] == before_document
    assert document[14:] == (None, None, None, None)
    assert embeddings == 0


def test_failed_v19_migration_restores_v18_schema_and_legacy_vectors(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "interrupted-v19"
    monkeypatch.setattr(migration_module, "LATEST_SCHEMA_VERSION", 18)
    legacy = ProjectRepository.create(root, "Interrupted v19")
    document_id = _insert_v15_memory_document(legacy)
    with legacy.database.connect() as connection, connection:
        connection.execute(
            """
            INSERT INTO memory_embeddings VALUES (
                ?, 'embedding-model', 2, '[1.0,0.0]', ?, 'CURRENT',
                '2026-08-09T00:00:00+00:00', '2026-08-09T00:00:00+00:00'
            )
            """,
            (document_id, "a" * 64),
        )

    monkeypatch.setattr(migration_module, "LATEST_SCHEMA_VERSION", 19)
    real_migration = migration_module.MIGRATIONS[19]

    def fail_during_migration(connection: sqlite3.Connection) -> None:
        connection.execute(
            "ALTER TABLE memory_documents ADD COLUMN source_start INTEGER"
        )
        connection.execute("DROP TABLE memory_embeddings")
        raise RuntimeError("injected v19 migration interruption")

    monkeypatch.setitem(migration_module.MIGRATIONS, 19, fail_during_migration)
    with pytest.raises(RuntimeError, match="injected v19 migration interruption"):
        ProjectRepository.open(root)

    with sqlite3.connect(root / "project.sqlite3") as connection:
        version = int(connection.execute("PRAGMA user_version").fetchone()[0])
        document_columns = {
            str(row[1])
            for row in connection.execute("PRAGMA table_info(memory_documents)")
        }
        vector = connection.execute(
            """
            SELECT model_id, dimensions, vector_json
            FROM memory_embeddings
            WHERE document_id = ?
            """,
            (document_id,),
        ).fetchone()

    assert version == 18
    assert "source_start" not in document_columns
    assert tuple(vector) == ("embedding-model", 2, "[1.0,0.0]")

    monkeypatch.setitem(migration_module.MIGRATIONS, 19, real_migration)
    recovered = ProjectRepository.open(root)
    with recovered.database.connect() as connection:
        recovered_version = int(connection.execute("PRAGMA user_version").fetchone()[0])
        document_count = int(
            connection.execute(
                "SELECT COUNT(*) FROM memory_documents WHERE id = ?",
                (document_id,),
            ).fetchone()[0]
        )
        embedding_count = int(
            connection.execute("SELECT COUNT(*) FROM memory_embeddings").fetchone()[0]
        )

    assert recovered_version == 19
    assert document_count == 1
    assert embedding_count == 0


@pytest.mark.parametrize(
    "identity",
    [
        ("", "model", 1),
        ("provider", "", 1),
        ("provider", "model", 0),
        ("provider", "model", True),
        ("p" * 201, "model", 1),
        ("provider", "m" * 201, 1),
    ],
)
def test_embedding_index_identity_rejects_invalid_values(
    identity: tuple[object, object, object],
) -> None:
    with pytest.raises(ValueError, match="embedding"):
        EmbeddingIndexIdentity(*identity)  # type: ignore[arg-type]


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
