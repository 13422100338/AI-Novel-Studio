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
    OccurrenceRepositoryError,
)
from ai_novel_studio.infrastructure.storage.project_repository import ProjectRepository

CONTENT = "序章\n\n艾琳发现钥匙🔑。\n守卫随后封锁现场。"
REVISED = "序章\n\n艾琳发现钥匙🔑。\n守卫随后封锁了现场。"
NOW = datetime(2026, 8, 21, 8, 0, tzinfo=UTC)


def _hash(content: str) -> str:
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


@dataclass(frozen=True, slots=True)
class Fixture:
    project: ProjectRepository
    chapter_id: str
    subject_ids: tuple[str, ...]


def _fixture(tmp_path: Path) -> Fixture:
    project = ProjectRepository.create(tmp_path / "project", "Occurrence invalidation")
    chapter = ChapterRepository(project).create_chapter(
        project.list_volumes()[0].id,
        "发现",
        content=CONTENT,
    )
    characters = CharacterMemoryRepository(project)
    subjects = tuple(
        characters.create_character(name).id for name in ("艾琳", "守卫")
    )
    return Fixture(project, chapter.id, subjects)


def _chapter_state(
    project: ProjectRepository, chapter_id: str
) -> tuple[int, str]:
    with project.database.connect() as connection:
        row = connection.execute(
            "SELECT revision, content_hash FROM chapters WHERE id = ?",
            (chapter_id,),
        ).fetchone()
    assert row is not None
    return int(row["revision"]), str(row["content_hash"])


def _occurrence(
    chapter_id: str,
    revision: int,
    source_hash: str,
    *,
    tag: str,
) -> Occurrence:
    start = CONTENT.index("艾琳")
    return Occurrence(
        id=new_id(),
        candidate_source_id=f"semantic-window:{chapter_id}:r{revision}:occ:{tag}",
        type_code=OccurrenceType.DISCOVERY,
        vocabulary_version=OCCURRENCE_TYPE_VOCABULARY_V1,
        title="发现钥匙",
        summary="艾琳发现了带有标记的钥匙。",
        narrative_sequence=1,
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
                semantic_window_source_id=f"semantic-window:{chapter_id}:r{revision}:{tag}",
                policy_version="semantic-window-v1",
                source_start=start,
                source_end=start + len("艾琳发现钥匙🔑。"),
            ),
        ),
        created_at=NOW,
        updated_at=NOW,
    )


def _link(
    chapter_id: str,
    revision: int,
    source_hash: str,
    occurrence: Occurrence,
    subject_id: str,
    *,
    tag: str,
) -> SubjectOccurrenceLink:
    start = CONTENT.index("艾琳")
    return SubjectOccurrenceLink(
        id=new_id(),
        candidate_source_id=f"semantic-window:{chapter_id}:r{revision}:link:{tag}",
        occurrence_id=occurrence.id,
        subject_id=subject_id,
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
                semantic_window_source_id=f"semantic-window:{chapter_id}:r{revision}:{tag}",
                policy_version="semantic-window-v1",
                source_start=start,
                source_end=start + len("艾琳"),
            ),
        ),
        created_at=NOW,
        updated_at=NOW,
    )


@dataclass(frozen=True, slots=True)
class Batch:
    review: Occurrence
    approved: Occurrence
    locked: Occurrence
    rejected: Occurrence
    link_review: SubjectOccurrenceLink
    link_approved: SubjectOccurrenceLink


def _persist_batch(
    project: ProjectRepository,
    chapter_id: str,
    subject_ids: tuple[str, ...],
    *,
    tag: str,
) -> Batch:
    revision, source_hash = _chapter_state(project, chapter_id)
    review = _occurrence(chapter_id, revision, source_hash, tag=f"{tag}-rev")
    approved = _occurrence(chapter_id, revision, source_hash, tag=f"{tag}-app")
    locked = _occurrence(chapter_id, revision, source_hash, tag=f"{tag}-lock")
    rejected = _occurrence(chapter_id, revision, source_hash, tag=f"{tag}-rej")
    link_review = _link(
        chapter_id, revision, source_hash, review, subject_ids[0], tag=f"{tag}-rev"
    )
    link_approved = _link(
        chapter_id, revision, source_hash, approved, subject_ids[1], tag=f"{tag}-app"
    )
    OccurrenceRepository(project).create_model_candidates_for_chapter(
        chapter_id,
        expected_revision=revision,
        expected_source_hash=source_hash,
        occurrences=(review, approved, locked, rejected),
        links=(link_review, link_approved),
    )
    with project.database.connect() as connection, connection:
        connection.execute(
            "UPDATE occurrences SET review_status = 'APPROVED' WHERE id = ?",
            (approved.id,),
        )
        connection.execute(
            "UPDATE occurrences SET review_status = 'LOCKED' WHERE id = ?",
            (locked.id,),
        )
        connection.execute(
            "UPDATE occurrences SET review_status = 'REJECTED' WHERE id = ?",
            (rejected.id,),
        )
        connection.execute(
            "UPDATE subject_occurrence_links SET review_status = 'APPROVED' "
            "WHERE id = ?",
            (link_approved.id,),
        )
    return Batch(review, approved, locked, rejected, link_review, link_approved)


def _row_flags(
    project: ProjectRepository,
    table: str,
    record_id: str,
) -> tuple[str, bool, bool, str]:
    with project.database.connect() as connection:
        row = connection.execute(
            f"SELECT review_status, stale, source_changed, updated_at "
            f"FROM {table} WHERE id = ?",
            (record_id,),
        ).fetchone()
    assert row is not None
    return (
        str(row["review_status"]),
        bool(row["stale"]),
        bool(row["source_changed"]),
        str(row["updated_at"]),
    )


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


def test_save_content_flags_old_revision_rows_and_dependencies(
    tmp_path: Path,
) -> None:
    fixture = _fixture(tmp_path)
    chapters = ChapterRepository(fixture.project)
    batch = _persist_batch(
        fixture.project, fixture.chapter_id, fixture.subject_ids, tag="b0"
    )

    chapters.save_content(
        fixture.chapter_id,
        REVISED,
        source="user_edit",
        reason="test revision",
        expected_revision=0,
    )

    status, stale, changed, updated = _row_flags(
        fixture.project, "occurrences", batch.review.id
    )
    assert (status, stale, changed) == ("REVIEW", True, False)
    assert updated > NOW.isoformat()
    assert _row_flags(fixture.project, "occurrences", batch.approved.id)[:3] == (
        "APPROVED",
        False,
        True,
    )
    assert _row_flags(fixture.project, "occurrences", batch.locked.id)[:3] == (
        "LOCKED",
        False,
        True,
    )
    assert _row_flags(fixture.project, "occurrences", batch.rejected.id)[:3] == (
        "REJECTED",
        True,
        False,
    )
    assert _row_flags(
        fixture.project, "subject_occurrence_links", batch.link_review.id
    )[:3] == ("REVIEW", True, False)
    assert _row_flags(
        fixture.project, "subject_occurrence_links", batch.link_approved.id
    )[:3] == ("APPROVED", False, True)
    assert (
        _dependency_status(fixture.project, "OCCURRENCE", batch.review.id) == "STALE"
    )
    assert (
        _dependency_status(
            fixture.project, "SUBJECT_OCCURRENCE_LINK", batch.link_review.id
        )
        == "STALE"
    )


def test_rename_chapter_flags_old_revision_rows(tmp_path: Path) -> None:
    fixture = _fixture(tmp_path)
    chapters = ChapterRepository(fixture.project)
    batch = _persist_batch(
        fixture.project, fixture.chapter_id, fixture.subject_ids, tag="b0"
    )

    chapters.rename_chapter(fixture.chapter_id, "发现之二")

    assert _row_flags(fixture.project, "occurrences", batch.review.id)[:3] == (
        "REVIEW",
        True,
        False,
    )
    assert _row_flags(fixture.project, "occurrences", batch.approved.id)[:3] == (
        "APPROVED",
        False,
        True,
    )
    assert _row_flags(
        fixture.project, "subject_occurrence_links", batch.link_review.id
    )[:3] == ("REVIEW", True, False)


def test_delete_volume_relocation_flags_old_revision_rows(tmp_path: Path) -> None:
    fixture = _fixture(tmp_path)
    chapters = ChapterRepository(fixture.project)
    batch = _persist_batch(
        fixture.project, fixture.chapter_id, fixture.subject_ids, tag="b0"
    )
    target_volume = fixture.project.create_volume("第二卷")

    chapters.delete_volume(
        fixture.project.list_volumes()[0].id,
        target_volume.id,
    )

    new_revision, _source_hash = _chapter_state(fixture.project, fixture.chapter_id)
    assert new_revision == 1
    assert _row_flags(fixture.project, "occurrences", batch.review.id)[:3] == (
        "REVIEW",
        True,
        False,
    )
    assert _row_flags(fixture.project, "occurrences", batch.approved.id)[:3] == (
        "APPROVED",
        False,
        True,
    )
    assert _row_flags(
        fixture.project, "subject_occurrence_links", batch.link_review.id
    )[:3] == ("REVIEW", True, False)


def test_second_invalidation_leaves_already_flagged_rows_untouched(
    tmp_path: Path,
) -> None:
    fixture = _fixture(tmp_path)
    chapters = ChapterRepository(fixture.project)
    batch = _persist_batch(
        fixture.project, fixture.chapter_id, fixture.subject_ids, tag="b0"
    )
    chapters.save_content(
        fixture.chapter_id,
        REVISED,
        source="user_edit",
        reason="first revision",
        expected_revision=0,
    )
    flagged_at = _row_flags(fixture.project, "occurrences", batch.review.id)[3]

    chapters.save_content(
        fixture.chapter_id,
        "序章\r\n\r\n第三次修改。",
        source="user_edit",
        reason="second revision",
        expected_revision=1,
    )

    assert _row_flags(fixture.project, "occurrences", batch.review.id)[3] == flagged_at
    assert _row_flags(fixture.project, "occurrences", batch.approved.id)[3] != ""


def test_new_revision_candidates_stay_current_while_old_stay_flagged(
    tmp_path: Path,
) -> None:
    fixture = _fixture(tmp_path)
    chapters = ChapterRepository(fixture.project)
    old = _persist_batch(
        fixture.project, fixture.chapter_id, fixture.subject_ids, tag="r0"
    )
    chapters.save_content(
        fixture.chapter_id,
        REVISED,
        source="user_edit",
        reason="test revision",
        expected_revision=0,
    )

    fresh = _persist_batch(
        fixture.project, fixture.chapter_id, fixture.subject_ids, tag="r1"
    )

    assert _row_flags(fixture.project, "occurrences", fresh.review.id)[:3] == (
        "REVIEW",
        False,
        False,
    )
    assert _dependency_status(
        fixture.project, "OCCURRENCE", fresh.review.id
    ) == "CURRENT"
    assert _row_flags(fixture.project, "occurrences", old.review.id)[:3] == (
        "REVIEW",
        True,
        False,
    )


def test_reads_hydrate_flagged_rows_and_current_filters_exclude(
    tmp_path: Path,
) -> None:
    fixture = _fixture(tmp_path)
    chapters = ChapterRepository(fixture.project)
    batch = _persist_batch(
        fixture.project, fixture.chapter_id, fixture.subject_ids, tag="b0"
    )
    chapters.save_content(
        fixture.chapter_id,
        REVISED,
        source="user_edit",
        reason="test revision",
        expected_revision=0,
    )
    repository = OccurrenceRepository(fixture.project)

    stored = repository.get_occurrence(batch.review.id)

    assert stored.stale is True
    assert stored.source_changed is False

    all_links = repository.list_links_for_occurrence(batch.review.id)
    current_links = repository.list_links_for_occurrence(
        batch.review.id,
        include_stale=False,
        include_source_changed=False,
    )

    assert tuple(item.id for item in all_links) == (batch.link_review.id,)
    assert current_links == ()


def test_replay_of_invalidated_batch_conflicts(tmp_path: Path) -> None:
    fixture = _fixture(tmp_path)
    chapters = ChapterRepository(fixture.project)
    revision, source_hash = _chapter_state(fixture.project, fixture.chapter_id)
    review = _occurrence(fixture.chapter_id, revision, source_hash, tag="re")
    link = _link(
        fixture.chapter_id, revision, source_hash, review, fixture.subject_ids[0], tag="re"
    )
    OccurrenceRepository(fixture.project).create_model_candidates_for_chapter(
        fixture.chapter_id,
        expected_revision=revision,
        expected_source_hash=source_hash,
        occurrences=(review,),
        links=(link,),
    )
    chapters.save_content(
        fixture.chapter_id,
        REVISED,
        source="user_edit",
        reason="test revision",
        expected_revision=revision,
    )

    with pytest.raises((ValueError, OccurrenceRepositoryError)):
        OccurrenceRepository(fixture.project).create_model_candidates_for_chapter(
            fixture.chapter_id,
            expected_revision=revision + 1,
            expected_source_hash=_hash(REVISED),
            occurrences=(review,),
            links=(link,),
        )

    assert _row_flags(fixture.project, "occurrences", review.id)[:3] == (
        "REVIEW",
        True,
        False,
    )
    with fixture.project.database.connect() as connection:
        count = int(
            connection.execute("SELECT COUNT(*) FROM occurrences").fetchone()[0]
        )
        link_count = int(
            connection.execute(
                "SELECT COUNT(*) FROM subject_occurrence_links"
            ).fetchone()[0]
        )
    assert count == 1
    assert link_count == 1


def test_failed_save_rolls_back_flags_and_content(tmp_path: Path) -> None:
    fixture = _fixture(tmp_path)
    chapters = ChapterRepository(fixture.project)
    batch = _persist_batch(
        fixture.project, fixture.chapter_id, fixture.subject_ids, tag="b0"
    )
    with fixture.project.database.connect() as connection, connection:
        connection.execute(
            "CREATE TRIGGER fail_occ_update BEFORE UPDATE ON occurrences "
            "BEGIN SELECT RAISE(ABORT, 'RAW_TRIGGER'); END"
        )

    with pytest.raises(sqlite3.IntegrityError):
        chapters.save_content(
            fixture.chapter_id,
            REVISED,
            source="user_edit",
            reason="failed revision",
            expected_revision=0,
        )

    revision, source_hash = _chapter_state(fixture.project, fixture.chapter_id)
    assert revision == 0
    assert source_hash == _hash(CONTENT)
    assert chapters.read_content_exact(fixture.chapter_id) == CONTENT
    assert _row_flags(fixture.project, "occurrences", batch.review.id)[:3] == (
        "REVIEW",
        False,
        False,
    )
    assert (
        _dependency_status(fixture.project, "OCCURRENCE", batch.review.id) == "CURRENT"
    )
