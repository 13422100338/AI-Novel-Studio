from __future__ import annotations

import hashlib
import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

import pytest

from ai_novel_studio.domain.identifiers import new_id
from ai_novel_studio.domain.memory import Authority, ReviewStatus, SourceType
from ai_novel_studio.domain.occurrence import (
    OCCURRENCE_TYPE_VOCABULARY_V1,
    Occurrence,
    OccurrenceSourceRange,
    OccurrenceType,
)
from ai_novel_studio.infrastructure.storage.chapter_repository import ChapterRepository
from ai_novel_studio.infrastructure.storage.character_memory_repository import (
    CharacterMemoryRepository,
)
from ai_novel_studio.infrastructure.storage.database import Database
from ai_novel_studio.infrastructure.storage.occurrence_repository import (
    OccurrenceRepository,
    OccurrenceRepositoryError,
)
from ai_novel_studio.infrastructure.storage.project_repository import ProjectRepository

CONTENT = "序章\n\n艾琳发现钥匙🔑。\n守卫随后封锁现场。"
NOW = datetime(2026, 8, 21, 8, 0, tzinfo=UTC)


def _hash(content: str) -> str:
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


@dataclass(frozen=True, slots=True)
class Fixture:
    project: ProjectRepository
    chapter_ids: tuple[str, ...]


def _fixture(tmp_path: Path) -> Fixture:
    project = ProjectRepository.create(tmp_path / "project", "Occurrence review reads")
    chapters = ChapterRepository(project)
    first = chapters.create_chapter(
        project.list_volumes()[0].id,
        "第一章",
        content=CONTENT,
    )
    second = chapters.create_chapter(
        project.list_volumes()[0].id,
        "第二章",
        content=CONTENT,
    )
    CharacterMemoryRepository(project).create_character("艾琳")
    return Fixture(project, (first.id, second.id))


def _chapter_state(
    project: ProjectRepository, chapter_id: str
) -> tuple[int, str, int]:
    with project.database.connect() as connection:
        row = connection.execute(
            """
            SELECT c.revision, c.content_hash,
                   1 + (
                       SELECT COUNT(*)
                       FROM chapters preceding
                       JOIN volumes preceding_volume
                         ON preceding_volume.id = preceding.volume_id
                       WHERE preceding.is_deleted = 0
                         AND (
                             preceding_volume.sort_index < volume.sort_index
                             OR (
                                 preceding_volume.sort_index = volume.sort_index
                                 AND preceding.sort_index < c.sort_index
                             )
                         )
                   ) AS narrative_sequence
            FROM chapters c
            JOIN volumes volume ON volume.id = c.volume_id
            WHERE c.id = ? AND c.is_deleted = 0
            """,
            (chapter_id,),
        ).fetchone()
    assert row is not None
    return int(row["revision"]), str(row["content_hash"]), int(row["narrative_sequence"])


def _occurrence(
    chapter_id: str,
    revision: int,
    source_hash: str,
    narrative_sequence: int,
    *,
    tag: str,
) -> Occurrence:
    start = CONTENT.index("艾琳")
    return Occurrence(
        id=new_id(),
        candidate_source_id=f"semantic-window:{chapter_id}:occ:{tag}",
        type_code=OccurrenceType.DISCOVERY,
        vocabulary_version=OCCURRENCE_TYPE_VOCABULARY_V1,
        title="发现钥匙",
        summary="艾琳发现了带有标记的钥匙。",
        narrative_sequence=narrative_sequence,
        authority=Authority.MODEL_EXTRACTED,
        review_status=ReviewStatus.REVIEW,
        source_type=SourceType.MODEL,
        stale=False,
        source_changed=False,
        source_ranges=(
            OccurrenceSourceRange(
                ordinal=0,
                source_chapter_id=chapter_id,
                source_revision=revision,
                source_hash=source_hash,
                semantic_window_source_id=f"semantic-window:{chapter_id}:{tag}",
                policy_version="semantic-window-v1",
                source_start=start,
                source_end=start + len("艾琳发现钥匙🔑。"),
            ),
        ),
        created_at=NOW,
        updated_at=NOW,
    )


def _persist(
    fixture: Fixture,
    chapter_index: int,
    *,
    tag: str,
) -> Occurrence:
    chapter_id = fixture.chapter_ids[chapter_index]
    revision, source_hash, sequence = _chapter_state(fixture.project, chapter_id)
    occurrence = _occurrence(
        chapter_id, revision, source_hash, sequence, tag=tag
    )
    OccurrenceRepository(fixture.project).create_model_candidates_for_chapter(
        chapter_id,
        expected_revision=revision,
        expected_source_hash=source_hash,
        occurrences=(occurrence,),
        links=(),
    )
    return occurrence


def test_returns_only_fresh_review_in_canonical_order(tmp_path: Path) -> None:
    fixture = _fixture(tmp_path)
    repository = OccurrenceRepository(fixture.project)
    early = _persist(fixture, 0, tag="early")
    late = _persist(fixture, 1, tag="late")
    approved = _persist(fixture, 1, tag="approved")
    stale = _persist(fixture, 0, tag="stale")
    changed = _persist(fixture, 1, tag="changed")
    with fixture.project.database.connect() as connection, connection:
        connection.execute(
            "UPDATE occurrences SET review_status = 'APPROVED' WHERE id = ?",
            (approved.id,),
        )
        connection.execute(
            "UPDATE occurrences SET stale = 1 WHERE id = ?", (stale.id,)
        )
        connection.execute(
            "UPDATE occurrences SET source_changed = 1 WHERE id = ?",
            (changed.id,),
        )

    candidates = repository.list_review_candidates()

    assert tuple(item.id for item in candidates) == (early.id, late.id)
    assert all(item.review_status is ReviewStatus.REVIEW for item in candidates)


def test_empty_queue_returns_empty_tuple(tmp_path: Path) -> None:
    fixture = _fixture(tmp_path)

    assert OccurrenceRepository(fixture.project).list_review_candidates() == ()


def test_limit_is_validated_before_database_access(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fixture = _fixture(tmp_path)
    repository = OccurrenceRepository(fixture.project)

    def forbidden_connect(database: Database) -> sqlite3.Connection:
        raise AssertionError("invalid input reached database")

    monkeypatch.setattr(Database, "connect", forbidden_connect)
    for bad_limit in (True, 0, 501):
        with pytest.raises(ValueError):
            repository.list_review_candidates(limit=bad_limit)  # type: ignore[arg-type]


def test_limit_bounds_result(tmp_path: Path) -> None:
    fixture = _fixture(tmp_path)
    for index in range(4):
        _persist(fixture, index % 2, tag=f"tag{index}")

    candidates = OccurrenceRepository(fixture.project).list_review_candidates(limit=2)

    assert len(candidates) == 2


def test_corruption_fails_closed_with_sanitized_error(tmp_path: Path) -> None:
    fixture = _fixture(tmp_path)
    occurrence = _persist(fixture, 0, tag="corrupt")
    with fixture.project.database.connect() as connection, connection:
        connection.execute("PRAGMA ignore_check_constraints = ON")
        connection.execute(
            "UPDATE occurrences SET title = ? WHERE id = ?",
            (sqlite3.Binary(b"RAW_TITLE_SECRET"), occurrence.id),
        )
    repository = OccurrenceRepository(fixture.project)

    with pytest.raises(OccurrenceRepositoryError) as captured:
        repository.list_review_candidates()

    assert str(captured.value) == "stored occurrence is invalid"
    assert captured.value.__cause__ is None
    assert "RAW_TITLE_SECRET" not in str(captured.value)
