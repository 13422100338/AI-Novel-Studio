from __future__ import annotations

import hashlib
import sqlite3
from datetime import UTC, datetime
from pathlib import Path

import pytest

from ai_novel_studio.application.chapter_revision_service import (
    ChapterRevisionService,
)
from ai_novel_studio.application.evidence_query_service import (
    EvidenceQueryService,
)
from ai_novel_studio.application.formal_manuscript_evidence_service import (
    EvidenceOutcome,
    FormalManuscriptEvidenceService,
)
from ai_novel_studio.application.subject_history_service import (
    SubjectHistoryDetail,
    SubjectHistoryIndexItem,
    SubjectHistoryParticipant,
    SubjectHistoryService,
    SubjectHistorySourceRange,
)
from ai_novel_studio.core.context.history_retriever import HistoryRetriever
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
from ai_novel_studio.infrastructure.storage.search_repository import SearchRepository

CONTENT = "序章\n\n艾琳发现钥匙🔑。\n守卫随后封锁现场。"
NOW = datetime(2026, 8, 21, 8, 0, tzinfo=UTC)


def _hash(content: str) -> str:
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


def _chapter_state(project: ProjectRepository, chapter_id: str) -> tuple[int, str, int]:
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


class Pair:
    def __init__(
        self,
        project: ProjectRepository,
        chapter_id: str,
        subject_id: str,
        *,
        tag: str,
    ) -> None:
        revision, source_hash, sequence = _chapter_state(project, chapter_id)
        start = CONTENT.index("艾琳")
        self.occurrence = Occurrence(
            id=new_id(),
            candidate_source_id=f"semantic-window:{chapter_id}:occ:{tag}",
            type_code=OccurrenceType.DISCOVERY,
            vocabulary_version=OCCURRENCE_TYPE_VOCABULARY_V1,
            title="发现钥匙",
            summary="艾琳发现了带有标记的钥匙。",
            narrative_sequence=sequence,
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
        self.link = SubjectOccurrenceLink(
            id=new_id(),
            candidate_source_id=f"semantic-window:{chapter_id}:link:{tag}",
            occurrence_id=self.occurrence.id,
            subject_id=subject_id,
            role="发现者",
            subject_summary="艾琳首先发现了钥匙。",
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
                    semantic_window_source_id=f"semantic-window:{chapter_id}:{tag}",
                    policy_version="semantic-window-v1",
                    source_start=start,
                    source_end=start + len("艾琳"),
                ),
            ),
            created_at=NOW,
            updated_at=NOW,
        )
        OccurrenceRepository(project).create_model_candidates_for_chapter(
            chapter_id,
            expected_revision=revision,
            expected_source_hash=source_hash,
            occurrences=(self.occurrence,),
            links=(self.link,),
        )

    def set_status(self, project: ProjectRepository, status: ReviewStatus) -> None:
        with project.database.connect() as connection, connection:
            connection.execute(
                "UPDATE occurrences SET review_status = ? WHERE id = ?",
                (status.value, self.occurrence.id),
            )
            connection.execute(
                "UPDATE subject_occurrence_links SET review_status = ? WHERE id = ?",
                (status.value, self.link.id),
            )

    def flag(self, project: ProjectRepository, *, stale: bool, changed: bool) -> None:
        with project.database.connect() as connection, connection:
            connection.execute(
                "UPDATE occurrences SET stale = ?, source_changed = ? WHERE id = ?",
                (int(stale), int(changed), self.occurrence.id),
            )
            connection.execute(
                "UPDATE subject_occurrence_links SET stale = ?, source_changed = ? "
                "WHERE id = ?",
                (int(stale), int(changed), self.link.id),
            )


def _fixture(tmp_path: Path) -> tuple[ProjectRepository, str, tuple[str, ...]]:
    project = ProjectRepository.create(tmp_path / "project", "Subject history")
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
    characters = CharacterMemoryRepository(project)
    subject_ids = tuple(
        characters.create_character(name).id for name in ("艾琳", "守卫")
    )
    return project, first.id, (second.id, *subject_ids)


def test_index_returns_compact_trusted_items_in_canonical_order(
    tmp_path: Path,
) -> None:
    project, first_chapter, other = _fixture(tmp_path)
    subject_id = other[1]
    early = Pair(project, first_chapter, subject_id, tag="early")
    late = Pair(project, other[0], subject_id, tag="late")
    Pair(project, first_chapter, subject_id, tag="review")
    rejected = Pair(project, other[0], subject_id, tag="rejected")
    early.set_status(project, ReviewStatus.APPROVED)
    late.set_status(project, ReviewStatus.LOCKED)
    rejected.set_status(project, ReviewStatus.REJECTED)
    service = SubjectHistoryService(project)

    items = service.list_index(subject_id)

    assert [item.occurrence_id for item in items] == [
        early.occurrence.id,
        late.occurrence.id,
    ]
    first_item = items[0]
    assert isinstance(first_item, SubjectHistoryIndexItem)
    assert first_item.occurrence_type is OccurrenceType.DISCOVERY
    assert first_item.narrative_sequence == 1
    assert first_item.title == "发现钥匙"
    assert first_item.role == "发现者"
    assert first_item.subject_summary == "艾琳首先发现了钥匙。"
    assert first_item.link_id == early.link.id
    assert first_item.review_status is ReviewStatus.APPROVED


def test_index_excludes_stale_and_source_changed_by_default(tmp_path: Path) -> None:
    project, first_chapter, other = _fixture(tmp_path)
    subject_id = other[1]
    current = Pair(project, first_chapter, subject_id, tag="current")
    stale = Pair(project, first_chapter, subject_id, tag="stale")
    changed = Pair(project, first_chapter, subject_id, tag="changed")
    current.set_status(project, ReviewStatus.APPROVED)
    stale.set_status(project, ReviewStatus.LOCKED)
    changed.set_status(project, ReviewStatus.LOCKED)
    stale.flag(project, stale=True, changed=False)
    changed.flag(project, stale=False, changed=True)
    service = SubjectHistoryService(project)

    items = service.list_index(subject_id)

    assert [item.occurrence_id for item in items] == [current.occurrence.id]


def test_review_statuses_override_allows_review_queue(tmp_path: Path) -> None:
    project, first_chapter, other = _fixture(tmp_path)
    subject_id = other[1]
    pending = Pair(project, first_chapter, subject_id, tag="pending")
    approved = Pair(project, first_chapter, subject_id, tag="approved")
    approved.set_status(project, ReviewStatus.APPROVED)
    service = SubjectHistoryService(project)

    items = service.list_index(
        subject_id,
        review_statuses=(ReviewStatus.REVIEW,),
    )

    assert [item.occurrence_id for item in items] == [pending.occurrence.id]
    assert items[0].review_status is ReviewStatus.REVIEW


def test_unknown_subject_raises_fixed_keyerror_and_invalid_id_fails_before_db(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project, first_chapter, other = _fixture(tmp_path)
    service = SubjectHistoryService(project)

    with pytest.raises(KeyError) as captured:
        service.list_index(new_id())
    assert captured.value.args == ("unknown subject",)

    def forbidden_connect(database: Database) -> sqlite3.Connection:
        raise AssertionError("invalid input reached database")

    monkeypatch.setattr(Database, "connect", forbidden_connect)
    with pytest.raises(ValueError):
        service.list_index("not-a-uuid")


def test_limit_validated_before_db_and_bounds_result(tmp_path: Path) -> None:
    project, first_chapter, other = _fixture(tmp_path)
    subject_id = other[1]
    pairs = [
        Pair(project, first_chapter if index % 2 == 0 else other[0], subject_id, tag=f"t{index}")
        for index in range(4)
    ]
    for pair in pairs:
        pair.set_status(project, ReviewStatus.APPROVED)
    service = SubjectHistoryService(project)

    def forbidden_connect(database: Database) -> sqlite3.Connection:
        raise AssertionError("invalid input reached database")

    monkeypatch = pytest.MonkeyPatch()
    try:
        monkeypatch.setattr(Database, "connect", forbidden_connect)
        for bad_limit in (True, 0, 501):
            with pytest.raises(ValueError):
                service.list_index(subject_id, limit=bad_limit)  # type: ignore[arg-type]
    finally:
        monkeypatch.undo()

    items = service.list_index(subject_id, limit=2)
    assert len(items) == 2


def test_inactive_subject_history_remains_readable(tmp_path: Path) -> None:
    project, first_chapter, other = _fixture(tmp_path)
    subject_id = other[1]
    pair = Pair(project, first_chapter, subject_id, tag="inactive")
    pair.set_status(project, ReviewStatus.APPROVED)
    with project.database.connect() as connection, connection:
        connection.execute(
            "UPDATE subjects SET active = 0 WHERE id = ?", (subject_id,)
        )
    service = SubjectHistoryService(project)

    items = service.list_index(subject_id)

    assert [item.occurrence_id for item in items] == [pair.occurrence.id]


def test_index_items_are_body_free(tmp_path: Path) -> None:
    project, first_chapter, other = _fixture(tmp_path)
    subject_id = other[1]
    pair = Pair(project, first_chapter, subject_id, tag="bodyfree")
    pair.set_status(project, ReviewStatus.APPROVED)
    service = SubjectHistoryService(project)

    items = service.list_index(subject_id)

    field_names = {field.name for field in SubjectHistoryIndexItem.__dataclass_fields__.values()}  # type: ignore[attr-defined]
    assert {"body", "content", "quote", "summary_text", "manuscript"}.isdisjoint(
        field_names
    )
    assert all(
        item.subject_summary == "艾琳首先发现了钥匙。" and len(item.subject_summary) < 200
        for item in items
    )


def _detail_state(
    project: ProjectRepository, chapter_id: str
) -> tuple[int, str, int]:
    return _chapter_state(project, chapter_id)


def _add_links(
    project: ProjectRepository,
    occurrence: Occurrence,
    chapter_id: str,
    subject_ids: tuple[str, ...],
    *,
    tag_prefix: str,
    statuses: tuple[ReviewStatus, ...] | None = None,
) -> tuple[SubjectOccurrenceLink, ...]:
    revision, source_hash, _sequence = _chapter_state(project, chapter_id)
    start = CONTENT.index("艾琳")
    links = tuple(
        SubjectOccurrenceLink(
            id=new_id(),
            candidate_source_id=f"semantic-window:{chapter_id}:link:{tag_prefix}:{index}",
            occurrence_id=occurrence.id,
            subject_id=subject_ids[index],
            role=f"参与者{index}",
            subject_summary=f"参与者摘要{index}。",
            authority=Authority.MODEL_EXTRACTED,
            review_status=statuses[index] if statuses else ReviewStatus.REVIEW,
            source_type=SourceType.MODEL,
            stale=False,
            source_changed=False,
            source_ranges=(
                SubjectOccurrenceLinkSourceRange(
                    ordinal=0,
                    source_chapter_id=chapter_id,
                    source_revision=revision,
                    source_hash=source_hash,
                    semantic_window_source_id=f"semantic-window:{chapter_id}:{tag_prefix}",
                    policy_version="semantic-window-v1",
                    source_start=start,
                    source_end=start + len("艾琳"),
                ),
            ),
            created_at=NOW,
            updated_at=NOW,
        )
        for index in range(len(subject_ids))
    )
    OccurrenceRepository(project).create_model_candidates_for_chapter(
        chapter_id,
        expected_revision=revision,
        expected_source_hash=source_hash,
        occurrences=(occurrence,),
        links=links,
    )
    return links


def test_detail_returns_structured_trusted_occurrence_with_ordered_parts(
    tmp_path: Path,
) -> None:
    project, first_chapter, other = _fixture(tmp_path)
    first_subject, second_subject = other[1], other[2]
    pair = Pair(project, first_chapter, first_subject, tag="detail")
    extra = _add_links(
        project,
        pair.occurrence,
        first_chapter,
        (second_subject,),
        tag_prefix="zeta",
    )
    pair.set_status(project, ReviewStatus.LOCKED)
    with project.database.connect() as connection, connection:
        connection.execute(
            "UPDATE subject_occurrence_links SET review_status = 'LOCKED' "
            "WHERE id = ?",
            (extra[0].id,),
        )
    service = SubjectHistoryService(project)

    detail = service.get_detail(pair.occurrence.id)

    assert isinstance(detail, SubjectHistoryDetail)
    assert detail.occurrence_id == pair.occurrence.id
    assert detail.narrative_sequence == 1
    assert detail.occurrence_type is OccurrenceType.DISCOVERY
    assert detail.title == "发现钥匙"
    assert detail.summary == "艾琳发现了带有标记的钥匙。"
    assert detail.review_status is ReviewStatus.LOCKED
    assert [item.subject_id for item in detail.participants] == [
        first_subject,
        second_subject,
    ]
    assert all(isinstance(item, SubjectHistoryParticipant) for item in detail.participants)
    first_participant = detail.participants[0]
    assert first_participant.link_id == pair.link.id
    assert first_participant.role == "发现者"
    assert first_participant.subject_summary == "艾琳首先发现了钥匙。"
    assert first_participant.review_status is ReviewStatus.LOCKED
    assert [item.link_id for item in detail.participants] == [
        pair.link.id,
        extra[0].id,
    ]
    source_range = detail.source_ranges[0]
    assert isinstance(source_range, SubjectHistorySourceRange)
    expected_revision, expected_hash, _sequence = _chapter_state(
        project, first_chapter
    )
    assert source_range.chapter_id == first_chapter
    assert source_range.revision == expected_revision
    assert source_range.source_hash == expected_hash
    assert source_range.semantic_window_source_id.endswith("detail")
    assert source_range.policy_version == "semantic-window-v1"
    start = CONTENT.index("艾琳")
    assert source_range.start == start
    assert source_range.end == start + len("艾琳发现钥匙🔑。")
    assert [
        (item.ordinal, item.source_start) for item in pair.occurrence.source_ranges
    ] == [(0, start)]


def test_detail_excludes_untrusted_statuses_by_default_and_override_reopens(
    tmp_path: Path,
) -> None:
    project, first_chapter, other = _fixture(tmp_path)
    subject_id = other[1]
    pending = Pair(project, first_chapter, subject_id, tag="pending")
    rejected = Pair(project, first_chapter, subject_id, tag="rejected")
    rejected.set_status(project, ReviewStatus.REJECTED)
    service = SubjectHistoryService(project)

    with pytest.raises(ValueError, match="unavailable"):
        service.get_detail(pending.occurrence.id)
    with pytest.raises(ValueError, match="unavailable"):
        service.get_detail(rejected.occurrence.id)

    reopened = service.get_detail(
        pending.occurrence.id,
        review_statuses=(ReviewStatus.REVIEW,),
    )
    assert reopened.review_status is ReviewStatus.REVIEW


def test_detail_excludes_stale_and_source_changed_by_default(tmp_path: Path) -> None:
    project, first_chapter, other = _fixture(tmp_path)
    subject_id = other[1]
    stale = Pair(project, first_chapter, subject_id, tag="stale")
    changed = Pair(project, first_chapter, subject_id, tag="changed")
    stale.set_status(project, ReviewStatus.APPROVED)
    changed.set_status(project, ReviewStatus.APPROVED)
    stale.flag(project, stale=True, changed=False)
    changed.flag(project, stale=False, changed=True)
    service = SubjectHistoryService(project)

    with pytest.raises(ValueError, match="unavailable"):
        service.get_detail(stale.occurrence.id)
    with pytest.raises(ValueError, match="unavailable"):
        service.get_detail(changed.occurrence.id)

    stale_detail = service.get_detail(stale.occurrence.id, include_stale=True)
    assert stale_detail.occurrence_id == stale.occurrence.id
    changed_detail = service.get_detail(
        changed.occurrence.id,
        include_source_changed=True,
    )
    assert changed_detail.occurrence_id == changed.occurrence.id


def test_detail_source_ranges_follow_ordinal_order(tmp_path: Path) -> None:
    project, first_chapter, other = _fixture(tmp_path)
    subject_id = other[1]
    revision, source_hash, sequence = _chapter_state(project, first_chapter)
    first_start = CONTENT.index("艾琳")
    second_start = CONTENT.index("守卫")
    occurrence = Occurrence(
        id=new_id(),
        candidate_source_id=f"semantic-window:{first_chapter}:occ:multirange",
        type_code=OccurrenceType.DISCOVERY,
        vocabulary_version=OCCURRENCE_TYPE_VOCABULARY_V1,
        title="发现钥匙",
        summary="艾琳发现了带有标记的钥匙。",
        narrative_sequence=sequence,
        authority=Authority.MODEL_EXTRACTED,
        review_status=ReviewStatus.REVIEW,
        source_type=SourceType.MODEL,
        stale=False,
        source_changed=False,
        source_ranges=(
            OccurrenceSourceRange(
                ordinal=0,
                source_chapter_id=first_chapter,
                source_revision=revision,
                source_hash=source_hash,
                semantic_window_source_id=f"semantic-window:{first_chapter}:multi",
                policy_version="semantic-window-v1",
                source_start=first_start,
                source_end=first_start + len("艾琳"),
            ),
            OccurrenceSourceRange(
                ordinal=1,
                source_chapter_id=first_chapter,
                source_revision=revision,
                source_hash=source_hash,
                semantic_window_source_id=f"semantic-window:{first_chapter}:multi",
                policy_version="semantic-window-v1",
                source_start=second_start,
                source_end=second_start + len("守卫"),
            ),
        ),
        created_at=NOW,
        updated_at=NOW,
    )
    link = SubjectOccurrenceLink(
        id=new_id(),
        candidate_source_id=f"semantic-window:{first_chapter}:link:multirange",
        occurrence_id=occurrence.id,
        subject_id=subject_id,
        role="发现者",
        subject_summary="艾琳首先发现了钥匙。",
        authority=Authority.MODEL_EXTRACTED,
        review_status=ReviewStatus.REVIEW,
        source_type=SourceType.MODEL,
        stale=False,
        source_changed=False,
        source_ranges=(
            SubjectOccurrenceLinkSourceRange(
                ordinal=0,
                source_chapter_id=first_chapter,
                source_revision=revision,
                source_hash=source_hash,
                semantic_window_source_id=f"semantic-window:{first_chapter}:multi",
                policy_version="semantic-window-v1",
                source_start=first_start,
                source_end=first_start + len("艾琳"),
            ),
        ),
        created_at=NOW,
        updated_at=NOW,
    )
    OccurrenceRepository(project).create_model_candidates_for_chapter(
        first_chapter,
        expected_revision=revision,
        expected_source_hash=source_hash,
        occurrences=(occurrence,),
        links=(link,),
    )
    with project.database.connect() as connection, connection:
        connection.execute(
            "UPDATE occurrences SET review_status = 'APPROVED' WHERE id = ?",
            (occurrence.id,),
        )

    detail = SubjectHistoryService(project).get_detail(occurrence.id)

    assert [(item.start, item.end) for item in detail.source_ranges] == [
        (first_start, first_start + len("艾琳")),
        (second_start, second_start + len("守卫")),
    ]


def test_detail_inactive_subject_link_remains_readable(tmp_path: Path) -> None:
    project, first_chapter, other = _fixture(tmp_path)
    subject_id = other[1]
    pair = Pair(project, first_chapter, subject_id, tag="inactive-detail")
    pair.set_status(project, ReviewStatus.APPROVED)
    with project.database.connect() as connection, connection:
        connection.execute(
            "UPDATE subjects SET active = 0 WHERE id = ?", (subject_id,)
        )

    detail = SubjectHistoryService(project).get_detail(pair.occurrence.id)

    assert [item.subject_id for item in detail.participants] == [subject_id]


def test_detail_unknown_id_raises_fixed_error_without_storage_echo(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project, first_chapter, other = _fixture(tmp_path)
    service = SubjectHistoryService(project)

    with pytest.raises(KeyError, match="unknown occurrence"):
        service.get_detail(new_id())

    from ai_novel_studio.infrastructure.storage.occurrence_repository import (
        OccurrenceRepositoryError,
    )

    def corrupted(*args, **kwargs):
        raise OccurrenceRepositoryError("RAW STORAGE SECRET")

    monkeypatch.setattr(OccurrenceRepository, "get_occurrence", corrupted)
    with pytest.raises(ValueError, match="unavailable"):
        service.get_detail(new_id())


def test_detail_participant_limit_validates_before_db_and_fails_explicit_overflow(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project, first_chapter, other = _fixture(tmp_path)
    service = SubjectHistoryService(project)

    def forbidden_connect(database: Database) -> sqlite3.Connection:
        raise AssertionError("invalid input reached database")

    monkeypatch.setattr(Database, "connect", forbidden_connect)
    for bad_limit in (True, 0, 101):
        with pytest.raises(ValueError, match="participant limit is invalid"):
            service.get_detail(new_id(), participant_limit=bad_limit)  # type: ignore[arg-type]

    monkeypatch.undo()

    characters = CharacterMemoryRepository(project)
    subjects = tuple(
        characters.create_character(f"路人{index}").id for index in range(3)
    )
    revision, source_hash, sequence = _chapter_state(project, first_chapter)
    start = CONTENT.index("艾琳")
    occurrence = Occurrence(
        id=new_id(),
        candidate_source_id=f"semantic-window:{first_chapter}:occ:overflow",
        type_code=OccurrenceType.DISCOVERY,
        vocabulary_version=OCCURRENCE_TYPE_VOCABULARY_V1,
        title="发现钥匙",
        summary="艾琳发现了带有标记的钥匙。",
        narrative_sequence=sequence,
        authority=Authority.MODEL_EXTRACTED,
        review_status=ReviewStatus.REVIEW,
        source_type=SourceType.MODEL,
        stale=False,
        source_changed=False,
        source_ranges=(
            OccurrenceSourceRange(
                ordinal=0,
                source_chapter_id=first_chapter,
                source_revision=revision,
                source_hash=source_hash,
                semantic_window_source_id=f"semantic-window:{first_chapter}:overflow",
                policy_version="semantic-window-v1",
                source_start=start,
                source_end=start + len("艾琳发现钥匙🔑。"),
            ),
        ),
        created_at=NOW,
        updated_at=NOW,
    )
    links = tuple(
        SubjectOccurrenceLink(
            id=new_id(),
            candidate_source_id=f"semantic-window:{first_chapter}:link:overflow:{index}",
            occurrence_id=occurrence.id,
            subject_id=subjects[index],
            role=f"参与者{index}",
            subject_summary=f"参与者摘要{index}。",
            authority=Authority.MODEL_EXTRACTED,
            review_status=ReviewStatus.REVIEW,
            source_type=SourceType.MODEL,
            stale=False,
            source_changed=False,
            source_ranges=(
                SubjectOccurrenceLinkSourceRange(
                    ordinal=0,
                    source_chapter_id=first_chapter,
                    source_revision=revision,
                    source_hash=source_hash,
                    semantic_window_source_id=(
                        f"semantic-window:{first_chapter}:overflow"
                    ),
                    policy_version="semantic-window-v1",
                    source_start=start,
                    source_end=start + len("艾琳"),
                ),
            ),
            created_at=NOW,
            updated_at=NOW,
        )
        for index in range(3)
    )
    OccurrenceRepository(project).create_model_candidates_for_chapter(
        first_chapter,
        expected_revision=revision,
        expected_source_hash=source_hash,
        occurrences=(occurrence,),
        links=links,
    )
    with project.database.connect() as connection, connection:
        connection.execute(
            "UPDATE occurrences SET review_status = 'APPROVED' WHERE id = ?",
            (occurrence.id,),
        )
        connection.execute(
            "UPDATE subject_occurrence_links SET review_status = 'APPROVED' "
            "WHERE occurrence_id = ?",
            (occurrence.id,),
        )

    with pytest.raises(ValueError, match="exceeds participant limit"):
        service.get_detail(occurrence.id, participant_limit=2)
    full = service.get_detail(occurrence.id, participant_limit=3)
    assert len(full.participants) == 3


def test_detail_never_opens_manuscript_files(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project, first_chapter, other = _fixture(tmp_path)
    subject_id = other[1]
    pair = Pair(project, first_chapter, subject_id, tag="nofiles")
    pair.set_status(project, ReviewStatus.APPROVED)

    def forbidden_read(*args, **kwargs):
        raise AssertionError("detail must not read manuscript files")

    monkeypatch.setattr(ChapterRepository, "read_content_exact", forbidden_read)

    detail = SubjectHistoryService(project).get_detail(pair.occurrence.id)

    assert detail.title == "发现钥匙"
    detail_fields = {
        item.name
        for item in SubjectHistoryDetail.__dataclass_fields__.values()  # type: ignore[attr-defined]
    }
    assert detail_fields.isdisjoint({"body", "content", "quote", "manuscript"})

EVIDENCE_BODIES = (
    "第一章\r\n\r\n艾琳在旧塔发现了铜钥匙。\r\n守卫没有察觉。\r\n",
    "第二章\r\n\r\n铜钥匙在井底发出微光。\r\n艾琳守卫对视一眼。\r\n",
    "第三章\r\n\r\n他们用铜钥匙打开了地窖。\r\n门后是空房间。\r\n",
)


def _evidence_fixture(
    tmp_path: Path,
) -> tuple[ProjectRepository, SubjectHistoryService, list[str], str]:
    project = ProjectRepository.create(tmp_path / "novel", "Subject evidence")
    revisions = ChapterRevisionService(project)
    chapter_ids: list[str] = []
    for index, body in enumerate(EVIDENCE_BODIES, start=1):
        submitted = revisions.submit_creation(
            project.list_volumes()[0].id,
            f"第{index}章",
            str(index),
            body,
        )
        chapter_ids.append(submitted.chapter.id)
    characters = CharacterMemoryRepository(project)
    subject_id = characters.create_character("艾琳").id
    search = SearchRepository(project)
    service = SubjectHistoryService(
        project,
        evidence_query=EvidenceQueryService(
            retriever=HistoryRetriever(search),
            evidence=FormalManuscriptEvidenceService(search),
        ),
    )
    return project, service, chapter_ids, subject_id


def _approved_occurrence_with_subject(
    project: ProjectRepository,
    chapter_id: str,
    subject_id: str,
    *,
    tag: str,
    title: str,
    summary: str,
) -> Occurrence:
    revision, source_hash, sequence = _chapter_state(project, chapter_id)
    occurrence = Occurrence(
        id=new_id(),
        candidate_source_id=f"semantic-window:{chapter_id}:occ:{tag}",
        type_code=OccurrenceType.DISCOVERY,
        vocabulary_version=OCCURRENCE_TYPE_VOCABULARY_V1,
        title=title,
        summary=summary,
        narrative_sequence=sequence,
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
                source_start=0,
                source_end=1,
            ),
        ),
        created_at=NOW,
        updated_at=NOW,
    )
    link = SubjectOccurrenceLink(
        id=new_id(),
        candidate_source_id=f"semantic-window:{chapter_id}:link:{tag}",
        occurrence_id=occurrence.id,
        subject_id=subject_id,
        role="发现者",
        subject_summary="人物中心投影。",
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
                semantic_window_source_id=f"semantic-window:{chapter_id}:{tag}",
                policy_version="semantic-window-v1",
                source_start=0,
                source_end=1,
            ),
        ),
        created_at=NOW,
        updated_at=NOW,
    )
    OccurrenceRepository(project).create_model_candidates_for_chapter(
        chapter_id,
        expected_revision=revision,
        expected_source_hash=source_hash,
        occurrences=(occurrence,),
        links=(link,),
    )
    with project.database.connect() as connection, connection:
        connection.execute(
            "UPDATE occurrences SET review_status = 'APPROVED' WHERE id = ?",
            (occurrence.id,),
        )
        connection.execute(
            "UPDATE subject_occurrence_links SET review_status = 'APPROVED' "
            "WHERE id = ?",
            (link.id,),
        )
    return occurrence


def test_get_evidence_returns_exact_current_hits_with_provenance(
    tmp_path: Path,
) -> None:
    project, service, chapter_ids, subject_id = _evidence_fixture(tmp_path)
    occurrence = _approved_occurrence_with_subject(
        project,
        chapter_ids[0],
        subject_id,
        tag="evidence",
        title="铜钥匙",
        summary="艾琳在旧塔发现了铜钥匙。",
    )

    result = service.get_evidence(occurrence.id, target_chapter_id=chapter_ids[2])

    assert result.outcome is EvidenceOutcome.FOUND
    assert result.hits
    assert all(hit.chapter_id in chapter_ids[:2] for hit in result.hits)
    body_by_chapter = dict(zip(chapter_ids, EVIDENCE_BODIES, strict=True))
    for hit in result.hits:
        assert hit.text == body_by_chapter[hit.chapter_id][
            hit.source_start : hit.source_end
        ]
        assert hit.retrieval_routes
        assert hit.document_id in hit.expanded_document_ids


def test_get_evidence_preserves_not_found_and_insufficient(
    tmp_path: Path,
) -> None:
    project, service, chapter_ids, subject_id = _evidence_fixture(tmp_path)
    missing = _approved_occurrence_with_subject(
        project,
        chapter_ids[0],
        subject_id,
        tag="missing",
        title="完全不存在的内容词组",
        summary="没有任何正文出现这个表达。",
    )
    known = _approved_occurrence_with_subject(
        project,
        chapter_ids[0],
        subject_id,
        tag="insufficient",
        title="铜钥匙",
        summary="艾琳在旧塔发现了铜钥匙。",
    )

    not_found = service.get_evidence(missing.id, target_chapter_id=chapter_ids[2])
    insufficient = service.get_evidence(
        known.id,
        target_chapter_id=chapter_ids[2],
        required_hits=8,
    )

    assert not_found.outcome is EvidenceOutcome.NOT_FOUND
    assert not_found.hits == ()
    assert insufficient.outcome is EvidenceOutcome.INSUFFICIENT
    assert 0 < len(insufficient.hits) < 8


def test_get_evidence_rejects_stale_and_untrusted_before_querying(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project, service, chapter_ids, subject_id = _evidence_fixture(tmp_path)
    occurrence = _approved_occurrence_with_subject(
        project,
        chapter_ids[0],
        subject_id,
        tag="stale-evidence",
        title="铜钥匙",
        summary="艾琳在旧塔发现了铜钥匙。",
    )
    pending = _approved_occurrence_with_subject(
        project,
        chapter_ids[0],
        subject_id,
        tag="pending-evidence",
        title="铜钥匙",
        summary="艾琳在旧塔发现了铜钥匙。",
    )
    with project.database.connect() as connection, connection:
        connection.execute(
            "UPDATE occurrences SET review_status = 'REVIEW', stale = 1 "
            "WHERE id = ?",
            (occurrence.id,),
        )
        connection.execute(
            "UPDATE occurrences SET review_status = 'REVIEW' WHERE id = ?",
            (pending.id,),
        )

    def forbidden_search(*args, **kwargs):
        raise AssertionError("untrusted occurrence must not reach retrieval")

    monkeypatch.setattr(HistoryRetriever, "search", forbidden_search)
    with pytest.raises(ValueError, match="unavailable"):
        service.get_evidence(occurrence.id, target_chapter_id=chapter_ids[2])
    with pytest.raises(ValueError, match="unavailable"):
        service.get_evidence(pending.id, target_chapter_id=chapter_ids[2])


def test_get_evidence_builds_query_from_title_and_summary(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project, service, chapter_ids, subject_id = _evidence_fixture(tmp_path)
    full = _approved_occurrence_with_subject(
        project,
        chapter_ids[0],
        subject_id,
        tag="query-full",
        title="铜钥匙",
        summary="艾琳在旧塔发现了铜钥匙。",
    )
    captured: list[tuple[str, str, tuple[str, ...]]] = []
    original_search = HistoryRetriever.search

    def recording(self_retriever, query, target_chapter_id, **kwargs):
        captured.append((query, target_chapter_id, kwargs.get("participants", ())))
        return original_search(self_retriever, query, target_chapter_id, **kwargs)

    monkeypatch.setattr(HistoryRetriever, "search", recording)

    service.get_evidence(full.id, target_chapter_id=chapter_ids[2])

    assert captured[0] == (
        "铜钥匙\n艾琳在旧塔发现了铜钥匙。",
        chapter_ids[2],
        (subject_id,),
    )

    from dataclasses import replace

    sparse_detail = replace(
        service.get_detail(full.id),
        title="地窖",
        summary="",
        participants=(),
    )
    monkeypatch.setattr(
        SubjectHistoryService,
        "get_detail",
        lambda self, occurrence_id, **kwargs: sparse_detail,
    )

    service.get_evidence(full.id, target_chapter_id=chapter_ids[2])

    assert captured[1] == ("地窖", chapter_ids[2], ())


def test_get_evidence_unknown_target_fails_closed_without_echo(
    tmp_path: Path,
) -> None:
    project, service, chapter_ids, subject_id = _evidence_fixture(tmp_path)
    occurrence = _approved_occurrence_with_subject(
        project,
        chapter_ids[0],
        subject_id,
        tag="unknown-target",
        title="铜钥匙",
        summary="艾琳在旧塔发现了铜钥匙。",
    )

    with pytest.raises(Exception) as captured_error:
        service.get_evidence(occurrence.id, target_chapter_id=new_id())

    assert "RAW" not in str(captured_error.value)


def test_get_evidence_requires_configured_service(tmp_path: Path) -> None:
    project, _service, chapter_ids, subject_id = _evidence_fixture(tmp_path)
    plain = SubjectHistoryService(project)
    occurrence = _approved_occurrence_with_subject(
        project,
        chapter_ids[0],
        subject_id,
        tag="plain-service",
        title="铜钥匙",
        summary="艾琳在旧塔发现了铜钥匙。",
    )

    with pytest.raises(ValueError, match="unavailable"):
        plain.get_evidence(occurrence.id, target_chapter_id=chapter_ids[2])
    with pytest.raises(TypeError, match="evidence"):
        SubjectHistoryService(project, evidence_query="invalid")  # type: ignore[arg-type]
