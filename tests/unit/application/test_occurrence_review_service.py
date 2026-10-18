from __future__ import annotations

import hashlib
import sqlite3
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path

import pytest

from ai_novel_studio.application.occurrence_review_service import (
    OccurrenceConflictError,
    OccurrenceNotFoundError,
    OccurrenceReviewError,
    OccurrenceReviewService,
    OccurrenceStaleError,
)
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
from ai_novel_studio.infrastructure.storage.database import Database
from ai_novel_studio.infrastructure.storage.occurrence_repository import (
    OccurrenceRepository,
)
from ai_novel_studio.infrastructure.storage.project_repository import ProjectRepository

CONTENT = "序章\r\n\r\n艾琳发现钥匙🔑。\r\n守卫随后封锁现场。"
NOW = datetime(2026, 8, 20, 8, 0, tzinfo=UTC)


def _hash(content: str) -> str:
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


def _fixture(tmp_path: Path) -> tuple[ProjectRepository, str, str, str, str]:
    project = ProjectRepository.create(tmp_path / "project", "Occurrence review")
    chapter = ChapterRepository(project).create_chapter(
        project.list_volumes()[0].id,
        "发现",
        content=CONTENT,
    )
    characters = CharacterMemoryRepository(project)
    first = characters.create_character("艾琳")
    second = characters.create_character("守卫")
    return project, chapter.id, first.id, second.id, _hash(CONTENT)


def _occurrence(
    chapter_id: str, revision: int, source_hash: str, narrative_sequence: int = 1
) -> Occurrence:
    start = CONTENT.index("艾琳")
    return Occurrence(
        id=new_id(),
        candidate_source_id=f"semantic-window:{chapter_id}:occurrence:{start}",
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
                semantic_window_source_id=f"semantic-window:{chapter_id}:0",
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
) -> SubjectOccurrenceLink:
    start = CONTENT.index("艾琳")
    return SubjectOccurrenceLink(
        id=new_id(),
        candidate_source_id=f"semantic-window:{chapter_id}:link:{subject_id[:8]}",
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
                semantic_window_source_id=f"semantic-window:{chapter_id}:0",
                policy_version="semantic-window-v1",
                source_start=start,
                source_end=start + len("艾琳"),
            ),
        ),
        created_at=NOW,
        updated_at=NOW,
    )


def _create(
    project: ProjectRepository,
    chapter_id: str,
    occ: Occurrence,
    link: SubjectOccurrenceLink | None = None,
) -> None:
    repo = OccurrenceRepository(project)
    with project.database.connect() as conn:
        row = conn.execute(
            "SELECT revision, content_hash FROM chapters WHERE id = ?",
            (chapter_id,),
        ).fetchone()
        rev = int(row["revision"])
        h = str(row["content_hash"])
    repo.create_model_candidates_for_chapter(
        chapter_id,
        expected_revision=rev,
        expected_source_hash=h,
        occurrences=(occ,),
        links=(link,) if link is not None else (),
    )


def test_review_occurrence_approves_with_expected_updated_at(tmp_path: Path) -> None:
    project, chapter_id, first_id, second_id, _ = _fixture(tmp_path)
    occ = _occurrence(chapter_id, 0, _hash(CONTENT))
    _create(project, chapter_id, occ)
    service = OccurrenceReviewService(project)
    stored = OccurrenceRepository(project).get_occurrence(occ.id)
    result = service.review_occurrence(
        occ.id,
        expected_updated_at=stored.updated_at.isoformat(),
        decision=ReviewStatus.APPROVED,
        confirmed_by_user=True,
    )
    assert result.occurrence.review_status == ReviewStatus.APPROVED
    assert result.occurrence.updated_at > stored.updated_at
    assert result.occurrence.stale is False


def test_review_occurrence_rejects(tmp_path: Path) -> None:
    project, chapter_id, first_id, *_ = _fixture(tmp_path)
    occ = _occurrence(chapter_id, 0, _hash(CONTENT))
    _create(project, chapter_id, occ)
    service = OccurrenceReviewService(project)
    stored = OccurrenceRepository(project).get_occurrence(occ.id)
    result = service.review_occurrence(
        occ.id,
        expected_updated_at=stored.updated_at.isoformat(),
        decision=ReviewStatus.REJECTED,
        confirmed_by_user=True,
    )
    assert result.occurrence.review_status == ReviewStatus.REJECTED


def test_review_occurrence_locks(tmp_path: Path) -> None:
    project, chapter_id, first_id, *_ = _fixture(tmp_path)
    occ = _occurrence(chapter_id, 0, _hash(CONTENT))
    _create(project, chapter_id, occ)
    service = OccurrenceReviewService(project)
    stored = OccurrenceRepository(project).get_occurrence(occ.id)
    result = service.review_occurrence(
        occ.id,
        expected_updated_at=stored.updated_at.isoformat(),
        decision=ReviewStatus.LOCKED,
        confirmed_by_user=True,
    )
    assert result.occurrence.review_status == ReviewStatus.LOCKED


def test_review_occurrence_not_found_is_fixed_error(tmp_path: Path) -> None:
    project, chapter_id, *_ = _fixture(tmp_path)
    service = OccurrenceReviewService(project)
    with pytest.raises(OccurrenceNotFoundError, match="occurrence not found"):
        service.review_occurrence(
            new_id(),
            expected_updated_at=NOW.isoformat(),
            decision=ReviewStatus.APPROVED,
            confirmed_by_user=True,
        )


def test_review_link_not_found_is_fixed_error(tmp_path: Path) -> None:
    project, chapter_id, *_ = _fixture(tmp_path)
    service = OccurrenceReviewService(project)
    with pytest.raises(OccurrenceNotFoundError, match="link not found"):
        service.review_link(
            new_id(),
            expected_updated_at=NOW.isoformat(),
            decision=ReviewStatus.APPROVED,
            confirmed_by_user=True,
        )


def test_review_blocks_stale_and_source_changed(tmp_path: Path) -> None:
    project, chapter_id, first_id, *_ = _fixture(tmp_path)
    occ = _occurrence(chapter_id, 0, _hash(CONTENT))
    _create(project, chapter_id, occ)
    with project.database.connect() as conn, conn:
        conn.execute("UPDATE occurrences SET stale = 1 WHERE id = ?", (occ.id,))
    service = OccurrenceReviewService(project)
    stored = occ.updated_at.isoformat()
    with pytest.raises(OccurrenceStaleError, match="occurrence source changed"):
        service.review_occurrence(
            occ.id,
            expected_updated_at=stored,
            decision=ReviewStatus.APPROVED,
            confirmed_by_user=True,
        )
    with project.database.connect() as conn, conn:
        conn.execute("UPDATE occurrences SET stale = 0, source_changed = 1 WHERE id = ?", (occ.id,))
    with pytest.raises(OccurrenceStaleError, match="occurrence source changed"):
        service.review_occurrence(
            occ.id,
            expected_updated_at=stored,
            decision=ReviewStatus.APPROVED,
            confirmed_by_user=True,
        )


def test_review_link_blocks_stale(tmp_path: Path) -> None:
    project, chapter_id, first_id, *_ = _fixture(tmp_path)
    occ = _occurrence(chapter_id, 0, _hash(CONTENT))
    link = _link(chapter_id, 0, _hash(CONTENT), occ, first_id)
    _create(project, chapter_id, occ, link)
    with project.database.connect() as conn, conn:
        conn.execute("UPDATE subject_occurrence_links SET stale = 1 WHERE id = ?", (link.id,))
    service = OccurrenceReviewService(project)
    with pytest.raises(OccurrenceStaleError, match="link source changed"):
        service.review_link(
            link.id,
            expected_updated_at=link.updated_at.isoformat(),
            decision=ReviewStatus.APPROVED,
            confirmed_by_user=True,
        )


def test_review_conflict_on_stale_updated_at(tmp_path: Path) -> None:
    project, chapter_id, first_id, *_ = _fixture(tmp_path)
    occ = _occurrence(chapter_id, 0, _hash(CONTENT))
    _create(project, chapter_id, occ)
    service = OccurrenceReviewService(project)
    stored = OccurrenceRepository(project).get_occurrence(occ.id)
    first = service.review_occurrence(
        occ.id,
        expected_updated_at=stored.updated_at.isoformat(),
        decision=ReviewStatus.APPROVED,
        confirmed_by_user=True,
    )
    assert first.occurrence.review_status == ReviewStatus.APPROVED
    with pytest.raises(OccurrenceConflictError, match="occurrence already reviewed"):
        service.review_occurrence(
            occ.id,
            expected_updated_at=stored.updated_at.isoformat(),
            decision=ReviewStatus.APPROVED,
            confirmed_by_user=True,
        )
    with pytest.raises(OccurrenceConflictError, match="occurrence already reviewed"):
        service.review_occurrence(
            occ.id,
            expected_updated_at=first.occurrence.updated_at.isoformat(),
            decision=ReviewStatus.REJECTED,
            confirmed_by_user=True,
        )


def test_review_link_conflict_on_already_reviewed(tmp_path: Path) -> None:
    project, chapter_id, first_id, *_ = _fixture(tmp_path)
    occ = _occurrence(chapter_id, 0, _hash(CONTENT))
    link = _link(chapter_id, 0, _hash(CONTENT), occ, first_id)
    _create(project, chapter_id, occ, link)
    service = OccurrenceReviewService(project)
    stored = OccurrenceRepository(project).list_links_for_occurrence(occ.id)[0]
    service.review_link(
        link.id,
        expected_updated_at=stored.updated_at.isoformat(),
        decision=ReviewStatus.APPROVED,
        confirmed_by_user=True,
    )
    with pytest.raises(OccurrenceConflictError, match="link already reviewed"):
        service.review_link(
            link.id,
            expected_updated_at=stored.updated_at.isoformat(),
            decision=ReviewStatus.APPROVED,
            confirmed_by_user=True,
        )


def test_review_requires_confirmed_by_user(tmp_path: Path) -> None:
    project, chapter_id, first_id, *_ = _fixture(tmp_path)
    occ = _occurrence(chapter_id, 0, _hash(CONTENT))
    _create(project, chapter_id, occ)
    service = OccurrenceReviewService(project)
    stored = OccurrenceRepository(project).get_occurrence(occ.id)
    with pytest.raises(PermissionError, match="confirmed by user"):
        service.review_occurrence(
            occ.id,
            expected_updated_at=stored.updated_at.isoformat(),
            decision=ReviewStatus.APPROVED,
            confirmed_by_user=False,
        )
    with pytest.raises(PermissionError):
        service.review_link(
            new_id(),
            expected_updated_at=NOW.isoformat(),
            decision=ReviewStatus.APPROVED,
            confirmed_by_user=False,
        )


def test_review_invalid_request_before_db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    project, chapter_id, first_id, *_ = _fixture(tmp_path)
    occ = _occurrence(chapter_id, 0, _hash(CONTENT))
    _create(project, chapter_id, occ)
    service = OccurrenceReviewService(project)

    def forbidden_connect(database: Database) -> sqlite3.Connection:
        raise AssertionError("invalid input reached database")

    monkeypatch.setattr(Database, "connect", forbidden_connect)
    with pytest.raises(OccurrenceReviewError, match="review request is invalid"):
        service.review_occurrence(
            "not-a-uuid",
            expected_updated_at=NOW.isoformat(),
            decision=ReviewStatus.APPROVED,
            confirmed_by_user=True,
        )
    with pytest.raises(OccurrenceReviewError, match="review request is invalid"):
        service.review_occurrence(
            occ.id,
            expected_updated_at="not-a-time",
            decision=ReviewStatus.APPROVED,
            confirmed_by_user=True,
        )
    with pytest.raises(OccurrenceReviewError, match="review request is invalid"):
        service.review_occurrence(
            occ.id,
            expected_updated_at=NOW.isoformat(),
            decision=ReviewStatus.REVIEW,  # type: ignore[arg-type]
            confirmed_by_user=True,
        )


def test_review_does_not_cascade(tmp_path: Path) -> None:
    project, chapter_id, first_id, second_id, _ = _fixture(tmp_path)
    occ = _occurrence(chapter_id, 0, _hash(CONTENT))
    link = _link(chapter_id, 0, _hash(CONTENT), occ, first_id)
    _create(project, chapter_id, occ, link)
    service = OccurrenceReviewService(project)
    occ_row = OccurrenceRepository(project).get_occurrence(occ.id)
    link_row = OccurrenceRepository(project).list_links_for_occurrence(occ.id)[0]
    service.review_occurrence(
        occ.id,
        expected_updated_at=occ_row.updated_at.isoformat(),
        decision=ReviewStatus.APPROVED,
        confirmed_by_user=True,
    )
    link_after = OccurrenceRepository(project).list_links_for_occurrence(occ.id)[0]
    assert link_after.review_status == ReviewStatus.REVIEW
    assert link_after.updated_at == link_row.updated_at
    service.review_link(
        link.id,
        expected_updated_at=link_row.updated_at.isoformat(),
        decision=ReviewStatus.APPROVED,
        confirmed_by_user=True,
    )
    occ_after = OccurrenceRepository(project).get_occurrence(occ.id)
    assert occ_after.review_status == ReviewStatus.APPROVED
    # second link still REVIEW proves no cascade
    occ2 = _occurrence(chapter_id, 0, _hash(CONTENT))
    occ2 = replace(
        occ2, candidate_source_id=f"semantic-window:{chapter_id}:occurrence:second"
    )
    link2 = _link(chapter_id, 0, _hash(CONTENT), occ2, second_id)
    _create(project, chapter_id, occ2, link2)
    assert (
        OccurrenceRepository(project).list_links_for_occurrence(occ2.id)[0].review_status
        == ReviewStatus.REVIEW
    )


def test_review_link_does_not_affect_occurrence(tmp_path: Path) -> None:
    project, chapter_id, first_id, *_ = _fixture(tmp_path)
    occ = _occurrence(chapter_id, 0, _hash(CONTENT))
    link = _link(chapter_id, 0, _hash(CONTENT), occ, first_id)
    _create(project, chapter_id, occ, link)
    service = OccurrenceReviewService(project)
    occ_before = OccurrenceRepository(project).get_occurrence(occ.id)
    link_before = OccurrenceRepository(project).list_links_for_occurrence(occ.id)[0]
    service.review_link(
        link.id,
        expected_updated_at=link_before.updated_at.isoformat(),
        decision=ReviewStatus.REJECTED,
        confirmed_by_user=True,
    )
    occ_after = OccurrenceRepository(project).get_occurrence(occ.id)
    assert occ_after.review_status == ReviewStatus.REVIEW
    assert occ_after.updated_at == occ_before.updated_at


def test_review_injected_failure_rolls_back(tmp_path: Path) -> None:
    project, chapter_id, first_id, *_ = _fixture(tmp_path)
    occ = _occurrence(chapter_id, 0, _hash(CONTENT))
    _create(project, chapter_id, occ)
    service = OccurrenceReviewService(project)
    stored = OccurrenceRepository(project).get_occurrence(occ.id)
    with project.database.connect() as conn, conn:
        conn.execute(
            "CREATE TRIGGER fail_occ_update BEFORE UPDATE ON occurrences "
            "BEGIN SELECT RAISE(ABORT, 'RAW_TRIGGER'); END"
        )
    with pytest.raises(OccurrenceReviewError, match="could not be saved"):
        service.review_occurrence(
            occ.id,
            expected_updated_at=stored.updated_at.isoformat(),
            decision=ReviewStatus.APPROVED,
            confirmed_by_user=True,
        )
    after = OccurrenceRepository(project).get_occurrence(occ.id)
    assert after.review_status == ReviewStatus.REVIEW
    assert after.updated_at == stored.updated_at
    assert "RAW_TRIGGER" not in str(after.updated_at)


def test_review_corruption_is_sanitized(tmp_path: Path) -> None:
    project, chapter_id, first_id, *_ = _fixture(tmp_path)
    occ = _occurrence(chapter_id, 0, _hash(CONTENT))
    _create(project, chapter_id, occ)
    with project.database.connect() as conn, conn:
        conn.execute("PRAGMA ignore_check_constraints = ON")
        conn.execute(
            "UPDATE occurrences SET title = ? WHERE id = ?",
            (sqlite3.Binary(b"bad"), occ.id),
        )
    service = OccurrenceReviewService(project)
    # corruption check
    with pytest.raises(OccurrenceReviewError):
        service.review_occurrence(
            occ.id,
            expected_updated_at=NOW.isoformat(),
            decision=ReviewStatus.APPROVED,
            confirmed_by_user=True,
        )
    # ensure not leaking raw bytes
    try:
        service.review_occurrence(
            occ.id,
            expected_updated_at=NOW.isoformat(),
            decision=ReviewStatus.APPROVED,
            confirmed_by_user=True,
        )
    except OccurrenceReviewError as e:
        assert "bad" not in str(e)
