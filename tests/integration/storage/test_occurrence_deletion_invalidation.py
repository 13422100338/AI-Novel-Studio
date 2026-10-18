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
    SubjectOccurrenceLink,
    SubjectOccurrenceLinkSourceRange,
)
from ai_novel_studio.infrastructure.storage.chapter_repository import ChapterRepository
from ai_novel_studio.infrastructure.storage.character_memory_repository import (
    CharacterMemoryRepository,
)
from ai_novel_studio.infrastructure.storage.occurrence_repository import (
    OccurrenceRepository,
)
from ai_novel_studio.infrastructure.storage.project_repository import ProjectRepository

CONTENT = "序章\n\n艾琳发现钥匙🔑。\n守卫随后封锁现场。"
OTHER = "另一章\n\n无关内容。\n"
NOW = datetime(2026, 8, 21, 8, 0, tzinfo=UTC)


def _hash(content: str) -> str:
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


@dataclass(frozen=True, slots=True)
class Fixture:
    project: ProjectRepository
    chapter_id: str
    other_chapter_id: str
    subject_ids: tuple[str, ...]


def _fixture(tmp_path: Path) -> Fixture:
    project = ProjectRepository.create(tmp_path / "project", "Occurrence deletion")
    chapters = ChapterRepository(project)
    chapter = chapters.create_chapter(
        project.list_volumes()[0].id,
        "发现",
        content=CONTENT,
    )
    other = chapters.create_chapter(
        project.list_volumes()[0].id,
        "另一章",
        content=OTHER,
    )
    characters = CharacterMemoryRepository(project)
    subject_ids = tuple(
        characters.create_character(name).id for name in ("艾琳", "守卫")
    )
    return Fixture(project, chapter.id, other.id, subject_ids)


def _row_flags(
    project: ProjectRepository,
    table: str,
    record_id: str,
) -> tuple[str, bool, bool]:
    with project.database.connect() as connection:
        row = connection.execute(
            f"SELECT review_status, stale, source_changed "
            f"FROM {table} WHERE id = ?",
            (record_id,),
        ).fetchone()
    assert row is not None
    return str(row["review_status"]), bool(row["stale"]), bool(row["source_changed"])


def _dependency_status(
    project: ProjectRepository,
    memory_type: str,
    memory_id: str,
) -> str:
    with project.database.connect() as connection:
        row = connection.execute(
            "SELECT status FROM memory_dependencies "
            "WHERE memory_type = ? AND memory_id = ?",
            (memory_type, memory_id),
        ).fetchone()
    assert row is not None
    return str(row["status"])


@dataclass(frozen=True, slots=True)
class Batch:
    review: Occurrence
    approved: Occurrence
    link_review: SubjectOccurrenceLink
    link_approved: SubjectOccurrenceLink


def _narrative_sequence(project: ProjectRepository, chapter_id: str) -> int:
    with project.database.connect() as connection:
        row = connection.execute(
            """
            SELECT 1 + (
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
    return int(row["narrative_sequence"])


def _persist_batch(
    fixture: Fixture,
    chapter_id: str,
    content: str,
    *,
    tag: str,
) -> Batch:
    with fixture.project.database.connect() as connection:
        row = connection.execute(
            "SELECT revision FROM chapters WHERE id = ?", (chapter_id,)
        ).fetchone()
    revision = int(row["revision"])
    source_hash = _hash(content)
    narrative_sequence = _narrative_sequence(fixture.project, chapter_id)
    start = content.index(content[:2])
    occurrences: list[Occurrence] = []
    links: list[SubjectOccurrenceLink] = []
    statuses = ("rev", "app")
    for index, status in enumerate(statuses):
        occurrence = Occurrence(
            id=new_id(),
            candidate_source_id=f"semantic-window:{chapter_id}:{tag}:{status}",
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
                    semantic_window_source_id=(
                        f"semantic-window:{chapter_id}:{tag}:{status}"
                    ),
                    policy_version="semantic-window-v1",
                    source_start=start,
                    source_end=start + len(content),
                ),
            ),
            created_at=NOW,
            updated_at=NOW,
        )
        occurrences.append(occurrence)
        links.append(
            SubjectOccurrenceLink(
                id=new_id(),
                candidate_source_id=f"semantic-window:{chapter_id}:{tag}:l{status}",
                occurrence_id=occurrence.id,
                subject_id=fixture.subject_ids[index],
                role="发现者",
                subject_summary="艾琳首先发现钥匙。",
                authority=Authority.MODEL_EXTRACTED,
                review_status=ReviewStatus.REVIEW,
                source_type=SourceType.MODEL,
                stale=False,
                source_changed=False,
                source_ranges=(
                    SubjectOccurrenceLinkSourceRange(
                        ordinal=0,
                        source_chapter_id=chapter_id,
                        source_revision=revision,
                        source_hash=source_hash,
                        semantic_window_source_id=(
                            f"semantic-window:{chapter_id}:{tag}:{status}"
                        ),
                        policy_version="semantic-window-v1",
                        source_start=start,
                        source_end=start + len(content[:2]),
                    ),
                ),
                created_at=NOW,
                updated_at=NOW,
            )
        )
    OccurrenceRepository(fixture.project).create_model_candidates_for_chapter(
        chapter_id,
        expected_revision=revision,
        expected_source_hash=source_hash,
        occurrences=tuple(occurrences),
        links=tuple(links),
    )
    with fixture.project.database.connect() as connection, connection:
        connection.execute(
            "UPDATE occurrences SET review_status = 'APPROVED' WHERE id = ?",
            (occurrences[1].id,),
        )
        connection.execute(
            "UPDATE subject_occurrence_links SET review_status = 'APPROVED' "
            "WHERE id = ?",
            (links[1].id,),
        )
    return Batch(occurrences[0], occurrences[1], links[0], links[1])


def test_delete_chapter_flags_bound_rows_and_stales_dependencies(
    tmp_path: Path,
) -> None:
    fixture = _fixture(tmp_path)
    batch = _persist_batch(fixture, fixture.chapter_id, CONTENT, tag="del")
    control = _persist_batch(fixture, fixture.other_chapter_id, OTHER, tag="ctl")

    ChapterRepository(fixture.project).delete_chapter(fixture.chapter_id)

    assert _row_flags(fixture.project, "occurrences", batch.review.id) == (
        "REVIEW",
        True,
        False,
    )
    assert _row_flags(fixture.project, "occurrences", batch.approved.id) == (
        "APPROVED",
        False,
        True,
    )
    assert _row_flags(
        fixture.project, "subject_occurrence_links", batch.link_review.id
    ) == ("REVIEW", True, False)
    assert _row_flags(
        fixture.project, "subject_occurrence_links", batch.link_approved.id
    ) == ("APPROVED", False, True)
    assert (
        _dependency_status(fixture.project, "OCCURRENCE", batch.review.id) == "STALE"
    )
    assert (
        _dependency_status(
            fixture.project, "SUBJECT_OCCURRENCE_LINK", batch.link_approved.id
        )
        == "STALE"
    )
    assert _row_flags(fixture.project, "occurrences", control.review.id) == (
        "REVIEW",
        False,
        False,
    )
    assert (
        _dependency_status(fixture.project, "OCCURRENCE", control.review.id)
        == "CURRENT"
    )


def test_restore_keeps_rows_stale_until_explicit_revalidation(
    tmp_path: Path,
) -> None:
    fixture = _fixture(tmp_path)
    chapters = ChapterRepository(fixture.project)
    older = _persist_batch(fixture, fixture.chapter_id, CONTENT, tag="older")
    revised_content = CONTENT + "\n追加段落。"
    chapters.save_content(
        fixture.chapter_id,
        revised_content,
        source="test",
        reason="advance revision",
    )
    batch = _persist_batch(fixture, fixture.chapter_id, revised_content, tag="cur")
    with fixture.project.database.connect() as connection, connection:
        connection.execute(
            "UPDATE occurrences SET stale = 1 WHERE id = ?", (older.review.id,)
        )
        connection.execute(
            "UPDATE memory_dependencies SET status = 'STALE' "
            "WHERE memory_type = 'OCCURRENCE' AND memory_id = ?",
            (older.review.id,),
        )

    chapters.delete_chapter(fixture.chapter_id)
    assert _row_flags(fixture.project, "occurrences", batch.review.id) == (
        "REVIEW",
        True,
        False,
    )
    chapters.restore_chapter(fixture.chapter_id)

    assert _row_flags(fixture.project, "occurrences", batch.review.id) == (
        "REVIEW",
        True,
        False,
    )
    assert _row_flags(fixture.project, "occurrences", batch.approved.id) == (
        "APPROVED",
        False,
        True,
    )
    assert (
        _dependency_status(fixture.project, "OCCURRENCE", batch.review.id)
        == "STALE"
    )
    assert _row_flags(fixture.project, "subject_occurrence_links", batch.link_review.id) == (
        "REVIEW",
        True,
        False,
    )
    assert _row_flags(fixture.project, "occurrences", older.review.id) == (
        "REVIEW",
        True,
        False,
    )


def test_failed_delete_rolls_back_flags_file_and_database(tmp_path: Path) -> None:
    fixture = _fixture(tmp_path)
    chapters = ChapterRepository(fixture.project)
    batch = _persist_batch(fixture, fixture.chapter_id, CONTENT, tag="fail")
    with fixture.project.database.connect() as connection, connection:
        connection.execute(
            "CREATE TRIGGER fail_occ_update BEFORE UPDATE ON occurrences "
            "BEGIN SELECT RAISE(ABORT, 'RAW_TRIGGER'); END"
        )

    with pytest.raises(sqlite3.IntegrityError):
        chapters.delete_chapter(fixture.chapter_id)

    stored = chapters.get_chapter(fixture.chapter_id)
    assert stored.is_deleted is False
    assert chapters.read_content_exact(fixture.chapter_id) == CONTENT
    assert _row_flags(fixture.project, "occurrences", batch.review.id) == (
        "REVIEW",
        False,
        False,
    )
    assert (
        _dependency_status(fixture.project, "OCCURRENCE", batch.review.id)
        == "CURRENT"
    )


def test_second_delete_restore_cycle_keeps_fail_closed_flags(tmp_path: Path) -> None:
    fixture = _fixture(tmp_path)
    chapters = ChapterRepository(fixture.project)
    batch = _persist_batch(fixture, fixture.chapter_id, CONTENT, tag="cycle")

    for _ in range(2):
        chapters.delete_chapter(fixture.chapter_id)
        assert _row_flags(fixture.project, "occurrences", batch.approved.id) == (
            "APPROVED",
            False,
            True,
        )
        chapters.restore_chapter(fixture.chapter_id)
        assert _row_flags(fixture.project, "occurrences", batch.approved.id) == (
            "APPROVED",
            False,
            True,
        )


def test_restore_never_clears_pre_existing_flags_on_matching_identity(
    tmp_path: Path,
) -> None:
    """预先失效（同 revision/hash）的行不得被 restore 自动恢复为 current。"""
    fixture = _fixture(tmp_path)
    chapters = ChapterRepository(fixture.project)
    batch = _persist_batch(fixture, fixture.chapter_id, CONTENT, tag="pre")
    with fixture.project.database.connect() as connection, connection:
        connection.execute(
            "UPDATE occurrences SET stale = 1 WHERE id = ?", (batch.approved.id,)
        )

    chapters.delete_chapter(fixture.chapter_id)
    chapters.restore_chapter(fixture.chapter_id)

    assert _row_flags(fixture.project, "occurrences", batch.approved.id) == (
        "APPROVED",
        True,
        False,
    )
