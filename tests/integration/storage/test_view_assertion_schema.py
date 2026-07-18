import sqlite3
from pathlib import Path

import pytest

from ai_novel_studio.infrastructure.storage.character_memory_repository import (
    CharacterMemoryRepository,
)
from ai_novel_studio.infrastructure.storage.migration_manager import (
    LATEST_SCHEMA_VERSION,
)
from ai_novel_studio.infrastructure.storage.project_repository import ProjectRepository


def _insert_assertion(
    connection: sqlite3.Connection,
    *,
    assertion_id: str,
    subject_id: str,
    view_type: str,
    viewer_subject_id: str | None = None,
    epistemic_status: str | None = None,
    visible_from: int | None = None,
) -> None:
    connection.execute(
        """
        INSERT INTO view_assertions (
            id, subject_id, view_type, viewer_subject_id, epistemic_status,
            content, narrative_visible_from_sequence, authority, review_status,
            source_type, source_id, source_revision, stale, source_changed,
            created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, 'fact', ?, 'USER_CONFIRMED', 'APPROVED',
                  'HUMAN', 'test', 0, 0, 0, '2026-01-01', '2026-01-01')
        """,
        (
            assertion_id,
            subject_id,
            view_type,
            viewer_subject_id,
            epistemic_status,
            visible_from,
        ),
    )


def test_schema_13_enforces_view_shapes_and_reader_reveal_time(tmp_path: Path) -> None:
    project = ProjectRepository.create(tmp_path / "project", "View schema")
    characters = CharacterMemoryRepository(project)
    subject = characters.create_character("Subject")
    viewer = characters.create_character("Viewer")

    with project.database.connect() as connection:
        version = connection.execute("PRAGMA user_version").fetchone()[0]
        _insert_assertion(
            connection,
            assertion_id="valid-character-view",
            subject_id=subject.id,
            view_type="CHARACTER_VIEW",
            viewer_subject_id=viewer.id,
            epistemic_status="KNOWS",
        )
        _insert_assertion(
            connection,
            assertion_id="valid-reader-view",
            subject_id=subject.id,
            view_type="READER_VIEW",
            visible_from=4,
        )
        with pytest.raises(sqlite3.IntegrityError):
            _insert_assertion(
                connection,
                assertion_id="missing-viewer",
                subject_id=subject.id,
                view_type="CHARACTER_VIEW",
            )
        with pytest.raises(sqlite3.IntegrityError):
            _insert_assertion(
                connection,
                assertion_id="premature-reader-view",
                subject_id=subject.id,
                view_type="READER_VIEW",
            )

    assert version == LATEST_SCHEMA_VERSION == 13
