import sqlite3
from collections.abc import Callable
from pathlib import Path

import pytest

import ai_novel_studio.infrastructure.storage.migration_manager as migration_module
from ai_novel_studio.infrastructure.storage.chapter_repository import ChapterRepository
from ai_novel_studio.infrastructure.storage.character_memory_repository import (
    CharacterMemoryRepository,
)
from ai_novel_studio.infrastructure.storage.project_repository import ProjectRepository

OCCURRENCE_ID = "00000000-0000-0000-0000-000000000101"
LINK_ID = "00000000-0000-0000-0000-000000000102"
CHAPTER_ID = "00000000-0000-0000-0000-000000000103"
TIMESTAMP = "2026-08-13T00:00:00+00:00"


def _columns(connection: sqlite3.Connection, table: str) -> tuple[str, ...]:
    return tuple(
        str(row[1]) for row in connection.execute(f"PRAGMA table_info({table})")
    )


def _primary_key(connection: sqlite3.Connection, table: str) -> tuple[str, ...]:
    rows = connection.execute(f"PRAGMA table_info({table})").fetchall()
    return tuple(
        str(row[1])
        for row in sorted(rows, key=lambda item: int(item[5]))
        if int(row[5]) > 0
    )


def _index_columns(
    connection: sqlite3.Connection,
    index: str,
) -> tuple[str, ...]:
    return tuple(
        str(row[2]) for row in connection.execute(f"PRAGMA index_info({index})")
    )


def _insert_model_occurrence(
    connection: sqlite3.Connection,
    *,
    occurrence_id: str = OCCURRENCE_ID,
    candidate_source_id: str = "window:occurrence:0",
    type_code: str = "DISCOVERY",
    vocabulary_version: str = "occurrence-type-v1",
    authority: str = "MODEL_EXTRACTED",
    review_status: str = "REVIEW",
    source_type: str = "MODEL",
) -> None:
    connection.execute(
        """
        INSERT INTO occurrences (
            id, candidate_source_id, type_code, vocabulary_version,
            title, summary, narrative_sequence, authority, review_status,
            source_type, stale, source_changed, created_at, updated_at
        ) VALUES (?, ?, ?, ?, 'Discovery', 'A hidden ledger is found.', 1,
                  ?, ?, ?, 0, 0, ?, ?)
        """,
        (
            occurrence_id,
            candidate_source_id,
            type_code,
            vocabulary_version,
            authority,
            review_status,
            source_type,
            TIMESTAMP,
            TIMESTAMP,
        ),
    )


def _insert_occurrence_range(
    connection: sqlite3.Connection,
    *,
    occurrence_id: str = OCCURRENCE_ID,
    ordinal: int = 0,
    source_chapter_id: str = CHAPTER_ID,
) -> None:
    connection.execute(
        """
        INSERT INTO occurrence_source_ranges (
            occurrence_id, ordinal, source_chapter_id, source_revision,
            source_hash, semantic_window_source_id, policy_version,
            source_start, source_end
        ) VALUES (?, ?, ?, 0, ?, 'SEMANTIC_WINDOW:source',
                  'semantic-window-v1', 1, 9)
        """,
        (occurrence_id, ordinal, source_chapter_id, "a" * 64),
    )


def _insert_link(
    connection: sqlite3.Connection,
    subject_id: str,
    *,
    link_id: str = LINK_ID,
    candidate_source_id: str = "window:participant-link:0",
    authority: str = "MODEL_EXTRACTED",
    review_status: str = "REVIEW",
    source_type: str = "MODEL",
) -> None:
    connection.execute(
        """
        INSERT INTO subject_occurrence_links (
            id, candidate_source_id, occurrence_id, subject_id, role,
            subject_summary, authority, review_status, source_type,
            stale, source_changed, created_at, updated_at
        ) VALUES (?, ?, ?, ?, 'witness', 'Witnesses the discovery.',
                  ?, ?, ?, 0, 0, ?, ?)
        """,
        (
            link_id,
            candidate_source_id,
            OCCURRENCE_ID,
            subject_id,
            authority,
            review_status,
            source_type,
            TIMESTAMP,
            TIMESTAMP,
        ),
    )


def _insert_link_range(
    connection: sqlite3.Connection,
    *,
    source_chapter_id: str = CHAPTER_ID,
) -> None:
    connection.execute(
        """
        INSERT INTO subject_occurrence_link_source_ranges (
            link_id, ordinal, source_chapter_id, source_revision, source_hash,
            semantic_window_source_id, policy_version, source_start, source_end
        ) VALUES (?, 0, ?, 0, ?, 'SEMANTIC_WINDOW:source',
                  'semantic-window-v1', 1, 9)
        """,
        (LINK_ID, source_chapter_id, "a" * 64),
    )


def test_schema_v20_adds_empty_occurrence_foundation_with_expected_shape(
    tmp_path: Path,
) -> None:
    project = ProjectRepository.create(tmp_path / "project", "Occurrence schema")

    with project.database.connect() as connection:
        version = int(connection.execute("PRAGMA user_version").fetchone()[0])
        table_names = {
            str(row[0])
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            )
        }
        occurrence_columns = _columns(connection, "occurrences")
        link_columns = _columns(connection, "subject_occurrence_links")
        occurrence_range_columns = _columns(connection, "occurrence_source_ranges")
        link_range_columns = _columns(
            connection,
            "subject_occurrence_link_source_ranges",
        )

    assert version == migration_module.LATEST_SCHEMA_VERSION == 20
    assert {
        "occurrences",
        "occurrence_source_ranges",
        "subject_occurrence_links",
        "subject_occurrence_link_source_ranges",
    } <= table_names
    assert occurrence_columns == (
        "id",
        "candidate_source_id",
        "type_code",
        "vocabulary_version",
        "title",
        "summary",
        "narrative_sequence",
        "authority",
        "review_status",
        "source_type",
        "stale",
        "source_changed",
        "created_at",
        "updated_at",
    )
    assert link_columns == (
        "id",
        "candidate_source_id",
        "occurrence_id",
        "subject_id",
        "role",
        "subject_summary",
        "authority",
        "review_status",
        "source_type",
        "stale",
        "source_changed",
        "created_at",
        "updated_at",
    )
    assert occurrence_range_columns == (
        "occurrence_id",
        "ordinal",
        "source_chapter_id",
        "source_revision",
        "source_hash",
        "semantic_window_source_id",
        "policy_version",
        "source_start",
        "source_end",
    )
    assert link_range_columns == (
        "link_id",
        "ordinal",
        "source_chapter_id",
        "source_revision",
        "source_hash",
        "semantic_window_source_id",
        "policy_version",
        "source_start",
        "source_end",
    )
    assert {"body", "content", "quote", "importance", "confidence"}.isdisjoint(
        set(occurrence_columns)
        | set(link_columns)
        | set(occurrence_range_columns)
        | set(link_range_columns)
    )


def test_schema_v20_enforces_keys_foreign_keys_uniques_and_indexes(
    tmp_path: Path,
) -> None:
    project = ProjectRepository.create(tmp_path / "project", "Occurrence constraints")
    character = CharacterMemoryRepository(project).create_character("Existing Character")
    chapter = ChapterRepository(project).create_chapter(
        project.list_volumes()[0].id,
        "Source",
        content="source body",
    )
    with project.database.connect() as connection, connection:
        _insert_model_occurrence(connection)
        _insert_occurrence_range(connection, source_chapter_id=chapter.id)
        _insert_link(connection, character.id)
        _insert_link_range(connection, source_chapter_id=chapter.id)

        assert _primary_key(connection, "occurrences") == ("id",)
        assert _primary_key(connection, "subject_occurrence_links") == ("id",)
        assert _primary_key(connection, "occurrence_source_ranges") == (
            "occurrence_id",
            "ordinal",
        )
        assert _primary_key(
            connection,
            "subject_occurrence_link_source_ranges",
        ) == ("link_id", "ordinal")
        assert _index_columns(
            connection,
            "occurrences_review_queue",
        ) == (
            "review_status",
            "stale",
            "source_changed",
            "narrative_sequence",
            "id",
        )
        assert _index_columns(
            connection,
            "occurrence_source_ranges_source",
        ) == ("source_chapter_id", "source_revision", "occurrence_id")
        assert _index_columns(
            connection,
            "subject_occurrence_links_subject_history",
        ) == (
            "subject_id",
            "review_status",
            "stale",
            "source_changed",
            "occurrence_id",
        )
        assert _index_columns(
            connection,
            "subject_occurrence_link_source_ranges_source",
        ) == ("source_chapter_id", "source_revision", "link_id")

        with pytest.raises(sqlite3.IntegrityError):
            _insert_model_occurrence(
                connection,
                occurrence_id="00000000-0000-0000-0000-000000000111",
            )
        with pytest.raises(sqlite3.IntegrityError):
            _insert_link(
                connection,
                character.id,
                link_id="00000000-0000-0000-0000-000000000112",
                candidate_source_id="window:participant-link:1",
            )
        with pytest.raises(sqlite3.IntegrityError):
            _insert_occurrence_range(connection, ordinal=1)
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute("DELETE FROM subjects WHERE id = ?", (character.id,))

        connection.execute(
            "DELETE FROM subject_occurrence_links WHERE id = ?",
            (LINK_ID,),
        )
        remaining_link_ranges = int(
            connection.execute(
                "SELECT COUNT(*) FROM subject_occurrence_link_source_ranges"
            ).fetchone()[0]
        )
        connection.execute("DELETE FROM occurrences WHERE id = ?", (OCCURRENCE_ID,))
        remaining_occurrence_ranges = int(
            connection.execute(
                "SELECT COUNT(*) FROM occurrence_source_ranges"
            ).fetchone()[0]
        )

    assert remaining_link_ranges == 0
    assert remaining_occurrence_ranges == 0


@pytest.mark.parametrize(
    ("authority", "source_type"),
    [
        ("USER_CONFIRMED", "MODEL"),
        ("MODEL_EXTRACTED", "HUMAN"),
    ],
)
def test_schema_v20_rejects_non_model_authority_or_source(
    tmp_path: Path,
    authority: str,
    source_type: str,
) -> None:
    project = ProjectRepository.create(tmp_path / "project", "Occurrence checks")

    with project.database.connect() as connection, connection:
        with pytest.raises(sqlite3.IntegrityError):
            _insert_model_occurrence(
                connection,
                authority=authority,
                source_type=source_type,
            )


@pytest.mark.parametrize(
    ("authority", "source_type"),
    [
        ("USER_CONFIRMED", "MODEL"),
        ("MODEL_EXTRACTED", "HUMAN"),
    ],
)
def test_schema_v20_rejects_non_model_authority_or_source_links(
    tmp_path: Path,
    authority: str,
    source_type: str,
) -> None:
    project = ProjectRepository.create(tmp_path / "project", "Link checks")
    character = CharacterMemoryRepository(project).create_character("Existing")

    with project.database.connect() as connection, connection:
        _insert_model_occurrence(connection)
        with pytest.raises(sqlite3.IntegrityError):
            _insert_link(
                connection,
                character.id,
                authority=authority,
                source_type=source_type,
            )


@pytest.mark.parametrize(
    "review_status",
    ("REVIEW", "APPROVED", "REJECTED", "LOCKED"),
)
def test_schema_v20_supports_the_full_review_lifecycle(
    tmp_path: Path,
    review_status: str,
) -> None:
    project = ProjectRepository.create(tmp_path / "project", "Review lifecycle")
    character = CharacterMemoryRepository(project).create_character("Existing")

    with project.database.connect() as connection, connection:
        _insert_model_occurrence(connection, review_status=review_status)
        _insert_link(connection, character.id, review_status=review_status)
        stored = connection.execute(
            """
            SELECT o.review_status, l.review_status
            FROM occurrences o
            JOIN subject_occurrence_links l ON l.occurrence_id = o.id
            """
        ).fetchone()

    assert tuple(stored) == (review_status, review_status)


@pytest.mark.parametrize("review_status", ("review", "PENDING", "", None))
def test_schema_v20_rejects_unknown_review_status(
    tmp_path: Path,
    review_status: object,
) -> None:
    project = ProjectRepository.create(tmp_path / "project", "Bad review status")

    with project.database.connect() as connection, connection:
        with pytest.raises(sqlite3.IntegrityError):
            _insert_model_occurrence(
                connection,
                review_status=review_status,  # type: ignore[arg-type]
            )


def test_schema_v20_keeps_database_vocabulary_open_but_subject_type_character_only(
    tmp_path: Path,
) -> None:
    project = ProjectRepository.create(tmp_path / "project", "Vocabulary checks")

    with project.database.connect() as connection, connection:
        _insert_model_occurrence(
            connection,
            type_code="FUTURE_CODE",
            vocabulary_version="occurrence-type-v2",
        )
        stored = connection.execute(
            "SELECT type_code, vocabulary_version FROM occurrences"
        ).fetchone()
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute(
                """
                INSERT INTO subjects (
                    id, type, canonical_name, active, created_at, updated_at
                ) VALUES ('event-subject', 'EVENT', 'Not allowed', 1, ?, ?)
                """,
                (TIMESTAMP, TIMESTAMP),
            )

    assert tuple(stored) == ("FUTURE_CODE", "occurrence-type-v2")


def test_v19_to_v20_is_additive_idempotent_and_preserves_legacy_rows(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "legacy-v19"
    monkeypatch.setattr(migration_module, "LATEST_SCHEMA_VERSION", 19)
    legacy = ProjectRepository.create(root, "Legacy v19")
    character = CharacterMemoryRepository(legacy).create_character(
        "Legacy Character",
        ("Legacy Alias",),
    )
    with legacy.database.connect() as connection:
        before_character = tuple(
            connection.execute(
                "SELECT * FROM characters WHERE id = ?",
                (character.id,),
            ).fetchone()
        )
        before_subject = tuple(
            connection.execute(
                "SELECT * FROM subjects WHERE id = ?",
                (character.id,),
            ).fetchone()
        )

    monkeypatch.setattr(migration_module, "LATEST_SCHEMA_VERSION", 20)
    migrated = ProjectRepository.open(root)
    reopened = ProjectRepository.open(root)

    with reopened.database.connect() as connection:
        version = int(connection.execute("PRAGMA user_version").fetchone()[0])
        migration_count = int(
            connection.execute(
                "SELECT COUNT(*) FROM schema_migrations WHERE version = 20"
            ).fetchone()[0]
        )
        after_character = tuple(
            connection.execute(
                "SELECT * FROM characters WHERE id = ?",
                (character.id,),
            ).fetchone()
        )
        after_subject = tuple(
            connection.execute(
                "SELECT * FROM subjects WHERE id = ?",
                (character.id,),
            ).fetchone()
        )
        occurrence_count = int(
            connection.execute("SELECT COUNT(*) FROM occurrences").fetchone()[0]
        )

    assert migrated.project == reopened.project
    assert version == 20
    assert migration_count == 1
    assert after_character == before_character
    assert after_subject == before_subject
    assert occurrence_count == 0


def test_failed_v20_migration_rolls_back_to_v19_and_retries(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "interrupted-v20"
    monkeypatch.setattr(migration_module, "LATEST_SCHEMA_VERSION", 19)
    legacy = ProjectRepository.create(root, "Interrupted v20")
    character = CharacterMemoryRepository(legacy).create_character("Preserved")
    real_migration: Callable[[sqlite3.Connection], None] = (
        migration_module.MIGRATIONS[20]
    )

    monkeypatch.setattr(migration_module, "LATEST_SCHEMA_VERSION", 20)

    def fail_after_v20_statements(connection: sqlite3.Connection) -> None:
        real_migration(connection)
        connection.execute("CREATE TABLE injected_after_v20 (id TEXT PRIMARY KEY)")
        raise RuntimeError("injected v20 migration interruption")

    monkeypatch.setitem(
        migration_module.MIGRATIONS,
        20,
        fail_after_v20_statements,
    )
    with pytest.raises(RuntimeError, match="injected v20 migration interruption"):
        ProjectRepository.open(root)

    with sqlite3.connect(root / "project.sqlite3") as connection:
        version_after_failure = int(
            connection.execute("PRAGMA user_version").fetchone()[0]
        )
        tables_after_failure = {
            str(row[0])
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            )
        }
        preserved_subject = connection.execute(
            "SELECT canonical_name FROM subjects WHERE id = ?",
            (character.id,),
        ).fetchone()

    assert version_after_failure == 19
    assert "occurrences" not in tables_after_failure
    assert "injected_after_v20" not in tables_after_failure
    assert tuple(preserved_subject) == ("Preserved",)

    monkeypatch.setitem(migration_module.MIGRATIONS, 20, real_migration)
    recovered = ProjectRepository.open(root)
    with recovered.database.connect() as connection:
        assert int(connection.execute("PRAGMA user_version").fetchone()[0]) == 20
        assert int(
            connection.execute(
                "SELECT COUNT(*) FROM schema_migrations WHERE version = 20"
            ).fetchone()[0]
        ) == 1


def test_future_schema_is_rejected_without_occurrence_migration(
    tmp_path: Path,
) -> None:
    root = tmp_path / "future"
    project = ProjectRepository.create(root, "Future")
    with sqlite3.connect(project.layout.database) as connection:
        connection.execute("PRAGMA user_version = 21")

    with pytest.raises(RuntimeError, match="newer schema"):
        ProjectRepository.open(root)
