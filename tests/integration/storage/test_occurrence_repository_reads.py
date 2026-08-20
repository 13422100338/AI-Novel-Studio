from __future__ import annotations

import hashlib
import sqlite3
from dataclasses import dataclass, fields, replace
from datetime import UTC, datetime
from pathlib import Path
from typing import NoReturn

import pytest

import ai_novel_studio.infrastructure.storage.occurrence_repository as occurrence_module
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
    OccurrenceRepositoryError,
)
from ai_novel_studio.infrastructure.storage.project_repository import ProjectRepository

CONTENT = "序章\r\n\r\n艾琳发现钥匙🔑。\r\n守卫随后封锁现场。"
NOW = datetime(2026, 8, 20, 8, 0, tzinfo=UTC)


def _hash(content: str) -> str:
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


@dataclass(frozen=True, slots=True)
class Fixture:
    project: ProjectRepository
    chapter_id: str
    revision: int
    source_hash: str
    narrative_sequence: int
    subject_ids: tuple[str, ...]


def _fixture(
    tmp_path: Path,
    *,
    subject_count: int = 4,
    content: str = CONTENT,
) -> Fixture:
    project = ProjectRepository.create(tmp_path / "project", "Occurrence reads")
    chapter = ChapterRepository(project).create_chapter(
        project.list_volumes()[0].id,
        "发现",
        content=content,
    )
    characters = CharacterMemoryRepository(project)
    subject_ids = tuple(
        characters.create_character(f"人物 {index}").id
        for index in range(subject_count)
    )
    return Fixture(
        project,
        chapter.id,
        chapter.revision,
        _hash(content),
        1,
        subject_ids,
    )


def _occurrence(
    fixture: Fixture,
    *,
    ordinal: int = 0,
    source_ranges: tuple[OccurrenceSourceRange, ...] | None = None,
) -> Occurrence:
    ranges = source_ranges or (
        OccurrenceSourceRange(
            ordinal=0,
            source_chapter_id=fixture.chapter_id,
            source_revision=fixture.revision,
            source_hash=fixture.source_hash,
            semantic_window_source_id=f"semantic-window:{fixture.chapter_id}:{ordinal}",
            policy_version="semantic-window-v1",
            source_start=0,
            source_end=2,
        ),
    )
    return Occurrence(
        id=new_id(),
        candidate_source_id=f"semantic-window:{fixture.chapter_id}:occurrence:{ordinal}",
        type_code=OccurrenceType.DISCOVERY,
        vocabulary_version=OCCURRENCE_TYPE_VOCABULARY_V1,
        title=f"事件 {ordinal}",
        summary=f"第 {ordinal} 个事件摘要。",
        narrative_sequence=fixture.narrative_sequence,
        authority=Authority.MODEL_EXTRACTED,
        review_status=ReviewStatus.REVIEW,
        source_type=SourceType.MODEL,
        stale=False,
        source_changed=False,
        source_ranges=ranges,
        created_at=NOW,
        updated_at=NOW,
    )


def _link(
    fixture: Fixture,
    occurrence: Occurrence,
    *,
    subject_id: str,
    ordinal: int,
) -> SubjectOccurrenceLink:
    return SubjectOccurrenceLink(
        id=new_id(),
        candidate_source_id=(
            f"semantic-window:{fixture.chapter_id}:participant-link:{ordinal}"
        ),
        occurrence_id=occurrence.id,
        subject_id=subject_id,
        role=f"角色 {ordinal}",
        subject_summary=f"人物在事件中的投影 {ordinal}。",
        authority=Authority.MODEL_EXTRACTED,
        review_status=ReviewStatus.REVIEW,
        source_type=SourceType.MODEL,
        stale=False,
        source_changed=False,
        source_ranges=(
            SubjectOccurrenceLinkSourceRange(
                ordinal=0,
                source_chapter_id=fixture.chapter_id,
                source_revision=fixture.revision,
                source_hash=fixture.source_hash,
                semantic_window_source_id=(
                    f"semantic-window:{fixture.chapter_id}:link:{ordinal}"
                ),
                policy_version="semantic-window-v1",
                source_start=2,
                source_end=4,
            ),
        ),
        created_at=NOW,
        updated_at=NOW,
    )


def _persist(
    fixture: Fixture,
    occurrences: tuple[Occurrence, ...],
    links: tuple[SubjectOccurrenceLink, ...],
) -> None:
    OccurrenceRepository(fixture.project).create_model_candidates_for_chapter(
        fixture.chapter_id,
        expected_revision=fixture.revision,
        expected_source_hash=fixture.source_hash,
        occurrences=occurrences,
        links=links,
    )


def _batch_for_subject(
    fixture: Fixture,
    count: int,
) -> tuple[tuple[Occurrence, ...], tuple[SubjectOccurrenceLink, ...]]:
    occurrences = tuple(_occurrence(fixture, ordinal=index) for index in range(count))
    links = tuple(
        _link(
            fixture,
            occurrence,
            subject_id=fixture.subject_ids[0],
            ordinal=index,
        )
        for index, occurrence in enumerate(occurrences)
    )
    return occurrences, links


def test_get_occurrence_is_lossless_body_free_and_never_reads_manuscript(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fixture = _fixture(tmp_path)
    first = OccurrenceSourceRange(
        0,
        fixture.chapter_id,
        fixture.revision,
        fixture.source_hash,
        "semantic-window:multi",
        "semantic-window-v1",
        0,
        2,
    )
    occurrence = _occurrence(
        fixture,
        source_ranges=(first, replace(first, ordinal=1, source_start=2, source_end=4)),
    )
    _persist(fixture, (occurrence,), ())
    with fixture.project.database.connect() as connection, connection:
        connection.execute(
            "UPDATE occurrences SET review_status = 'LOCKED' WHERE id = ?",
            (occurrence.id,),
        )
        connection.execute(
            "UPDATE memory_dependencies SET status = 'STALE' "
            "WHERE memory_type = 'OCCURRENCE' AND memory_id = ?",
            (occurrence.id,),
        )

    def forbidden_file_read(*args: object, **kwargs: object) -> NoReturn:
        raise AssertionError("read API attempted manuscript IO")

    monkeypatch.setattr(Path, "open", forbidden_file_read)
    stored = OccurrenceRepository(fixture.project).get_occurrence(occurrence.id)

    assert stored.review_status is ReviewStatus.LOCKED
    assert stored.source_ranges == occurrence.source_ranges
    assert {item.name for item in fields(stored)}.isdisjoint(
        {"body", "content", "quote"}
    )


def test_get_occurrence_distinguishes_invalid_unknown_and_valid_empty_inputs(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fixture = _fixture(tmp_path)
    repository = OccurrenceRepository(fixture.project)
    original_connect = Database.connect

    def forbidden_connect(database: Database) -> sqlite3.Connection:
        raise AssertionError("invalid input reached database")

    monkeypatch.setattr(Database, "connect", forbidden_connect)
    with pytest.raises(ValueError, match="occurrence record ID is invalid"):
        repository.get_occurrence("not-a-uuid")
    monkeypatch.setattr(Database, "connect", original_connect)

    with pytest.raises(KeyError) as captured:
        repository.get_occurrence(new_id())
    assert captured.value.args == ("unknown occurrence",)


def test_list_links_is_bounded_filtered_ordered_and_keeps_inactive_subjects(
    tmp_path: Path,
) -> None:
    fixture = _fixture(tmp_path)
    occurrence = _occurrence(fixture)
    links = tuple(
        _link(
            fixture,
            occurrence,
            subject_id=subject_id,
            ordinal=index,
        )
        for index, subject_id in enumerate(fixture.subject_ids)
    )
    _persist(fixture, (occurrence,), links)
    with fixture.project.database.connect() as connection, connection:
        connection.execute(
            "UPDATE subject_occurrence_links SET review_status = 'APPROVED' "
            "WHERE id = ?",
            (links[1].id,),
        )
        connection.execute(
            "UPDATE subject_occurrence_links SET review_status = 'REJECTED', stale = 1 "
            "WHERE id = ?",
            (links[2].id,),
        )
        connection.execute(
            "UPDATE subject_occurrence_links SET review_status = 'LOCKED', "
            "source_changed = 1 WHERE id = ?",
            (links[3].id,),
        )
        connection.execute(
            "UPDATE subjects SET active = 0 WHERE id = ?",
            (links[1].subject_id,),
        )
        connection.execute(
            "UPDATE memory_dependencies SET status = 'STALE' "
            "WHERE memory_type = 'SUBJECT_OCCURRENCE_LINK' AND memory_id = ?",
            (links[1].id,),
        )
    repository = OccurrenceRepository(fixture.project)

    all_links = repository.list_links_for_occurrence(occurrence.id, limit=4)
    current_review = repository.list_links_for_occurrence(
        occurrence.id,
        review_statuses=(ReviewStatus.REVIEW, ReviewStatus.APPROVED),
        include_stale=False,
        include_source_changed=False,
        limit=4,
    )

    assert tuple(item.candidate_source_id for item in all_links) == tuple(
        sorted(item.candidate_source_id for item in links)
    )
    assert {item.id for item in current_review} == {links[0].id, links[1].id}
    assert links[1].id in {item.id for item in all_links}


def test_list_links_distinguishes_unknown_parent_from_valid_no_links(
    tmp_path: Path,
) -> None:
    fixture = _fixture(tmp_path)
    occurrence = _occurrence(fixture)
    _persist(fixture, (occurrence,), ())
    repository = OccurrenceRepository(fixture.project)

    assert repository.list_links_for_occurrence(occurrence.id) == ()
    with pytest.raises(KeyError) as captured:
        repository.list_links_for_occurrence(new_id())
    assert captured.value.args == ("unknown occurrence",)


def test_list_subject_occurrences_uses_canonical_narrative_and_identity_order(
    tmp_path: Path,
) -> None:
    project = ProjectRepository.create(tmp_path / "project", "Subject ordering")
    chapters = ChapterRepository(project)
    subject_id = CharacterMemoryRepository(project).create_character("艾琳").id
    first_volume = project.list_volumes()[0]
    first_chapter = chapters.create_chapter(first_volume.id, "第一章", content=CONTENT)
    second_volume = project.create_volume("第二卷")
    second_chapter = chapters.create_chapter(second_volume.id, "第二章", content=CONTENT)

    fixtures = tuple(
        Fixture(
            project,
            chapter.id,
            chapter.revision,
            _hash(CONTENT),
            chapters.get_chapter_sequence(chapter.id),
            (subject_id,),
        )
        for chapter in (first_chapter, second_chapter)
    )
    first_late = _occurrence(fixtures[0], ordinal=9)
    first_early = _occurrence(fixtures[0], ordinal=1)
    second = _occurrence(fixtures[1], ordinal=0)
    for fixture, occurrences in (
        (fixtures[0], (first_late, first_early)),
        (fixtures[1], (second,)),
    ):
        links = tuple(
            _link(fixture, item, subject_id=subject_id, ordinal=index)
            for index, item in enumerate(occurrences)
        )
        _persist(fixture, occurrences, links)

    records = OccurrenceRepository(project).list_subject_occurrences(
        subject_id,
        limit=10,
    )

    assert all(
        isinstance(record, occurrence_module.SubjectOccurrenceRecord)
        for record in records
    )
    assert tuple(record.occurrence.id for record in records) == (
        first_early.id,
        first_late.id,
        second.id,
    )
    assert all(record.link.occurrence_id == record.occurrence.id for record in records)


def test_subject_occurrence_filters_are_independent_and_lossless_by_default(
    tmp_path: Path,
) -> None:
    fixture = _fixture(tmp_path, subject_count=1)
    occurrences, links = _batch_for_subject(fixture, 3)
    _persist(fixture, occurrences, links)
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
        connection.execute(
            "UPDATE occurrences SET review_status = 'REJECTED', stale = 1 "
            "WHERE id = ?",
            (occurrences[2].id,),
        )
        connection.execute(
            "UPDATE subject_occurrence_links SET review_status = 'LOCKED', "
            "source_changed = 1 WHERE id = ?",
            (links[2].id,),
        )
    repository = OccurrenceRepository(fixture.project)

    raw = repository.list_subject_occurrences(fixture.subject_ids[0], limit=10)
    approved = repository.list_subject_occurrences(
        fixture.subject_ids[0],
        occurrence_review_statuses=(ReviewStatus.APPROVED,),
        link_review_statuses=(ReviewStatus.APPROVED,),
        include_stale=False,
        include_source_changed=False,
        limit=10,
    )

    assert len(raw) == 3
    assert tuple(record.occurrence.id for record in approved) == (occurrences[1].id,)


def test_subject_occurrences_keep_inactive_history_but_unknown_subject_is_not_found(
    tmp_path: Path,
) -> None:
    fixture = _fixture(tmp_path, subject_count=1)
    occurrences, links = _batch_for_subject(fixture, 1)
    _persist(fixture, occurrences, links)
    with fixture.project.database.connect() as connection, connection:
        connection.execute(
            "UPDATE subjects SET active = 0 WHERE id = ?",
            (fixture.subject_ids[0],),
        )
    repository = OccurrenceRepository(fixture.project)

    assert len(repository.list_subject_occurrences(fixture.subject_ids[0])) == 1
    with pytest.raises(KeyError) as captured:
        repository.list_subject_occurrences(new_id())
    assert captured.value.args == ("unknown subject",)


def test_subject_occurrences_distinguish_corrupt_subject_from_not_found(
    tmp_path: Path,
) -> None:
    fixture = _fixture(tmp_path, subject_count=1)
    occurrences, links = _batch_for_subject(fixture, 1)
    _persist(fixture, occurrences, links)
    with fixture.project.database.connect() as connection, connection:
        connection.execute("PRAGMA ignore_check_constraints = ON")
        connection.execute(
            "UPDATE subjects SET type = ? WHERE id = ?",
            (sqlite3.Binary(b"RAW_SUBJECT_TYPE"), fixture.subject_ids[0]),
        )
    repository = OccurrenceRepository(fixture.project)

    with pytest.raises(OccurrenceRepositoryError) as captured:
        repository.list_subject_occurrences(fixture.subject_ids[0])

    assert str(captured.value) == "stored occurrence link is invalid"
    assert captured.value.__cause__ is None
    assert "RAW_SUBJECT_TYPE" not in str(captured.value)


@pytest.mark.parametrize(
    "corruption",
    (
        "occurrence_timestamp",
        "occurrence_scalar_type",
        "occurrence_range",
        "occurrence_dependency",
        "link_scalar_type",
        "link_range_identity",
        "link_dependency",
        "dangling_subject",
        "dangling_parent",
    ),
)
def test_read_corruption_fails_closed_with_fixed_sanitized_errors(
    tmp_path: Path,
    corruption: str,
) -> None:
    fixture = _fixture(tmp_path, subject_count=1)
    occurrence = _occurrence(fixture)
    link = _link(
        fixture,
        occurrence,
        subject_id=fixture.subject_ids[0],
        ordinal=0,
    )
    _persist(fixture, (occurrence,), (link,))
    with fixture.project.database.connect() as connection, connection:
        if corruption == "occurrence_timestamp":
            connection.execute(
                "UPDATE occurrences SET created_at = 'RAW_BODY_SECRET' WHERE id = ?",
                (occurrence.id,),
            )
        elif corruption == "occurrence_scalar_type":
            connection.execute("PRAGMA ignore_check_constraints = ON")
            connection.execute(
                "UPDATE occurrences SET title = ? WHERE id = ?",
                (sqlite3.Binary(b"123"), occurrence.id),
            )
        elif corruption == "occurrence_range":
            connection.execute(
                "DELETE FROM occurrence_source_ranges WHERE occurrence_id = ?",
                (occurrence.id,),
            )
        elif corruption == "occurrence_dependency":
            connection.execute(
                "DELETE FROM memory_dependencies WHERE memory_type = 'OCCURRENCE' "
                "AND memory_id = ?",
                (occurrence.id,),
            )
        elif corruption == "link_scalar_type":
            connection.execute("PRAGMA ignore_check_constraints = ON")
            connection.execute(
                "UPDATE subject_occurrence_links SET role = ? WHERE id = ?",
                (sqlite3.Binary(b"123"), link.id),
            )
        elif corruption == "link_range_identity":
            connection.execute(
                "UPDATE subject_occurrence_link_source_ranges SET source_hash = ? "
                "WHERE link_id = ?",
                ("f" * 64, link.id),
            )
        elif corruption == "link_dependency":
            connection.execute(
                "UPDATE memory_dependencies SET status = 'FAILED' "
                "WHERE memory_type = 'SUBJECT_OCCURRENCE_LINK' AND memory_id = ?",
                (link.id,),
            )
        elif corruption == "dangling_subject":
            connection.execute("PRAGMA foreign_keys = OFF")
            connection.execute("DELETE FROM subjects WHERE id = ?", (link.subject_id,))
        else:
            connection.execute("PRAGMA foreign_keys = OFF")
            connection.execute(
                "UPDATE subject_occurrence_links SET occurrence_id = ? WHERE id = ?",
                (new_id(), link.id),
            )
    repository = OccurrenceRepository(fixture.project)

    with pytest.raises(OccurrenceRepositoryError) as captured:
        if corruption.startswith("occurrence_"):
            repository.get_occurrence(occurrence.id)
        elif corruption == "dangling_parent":
            repository.list_subject_occurrences(link.subject_id)
        else:
            repository.list_links_for_occurrence(occurrence.id)

    expected = (
        "stored occurrence is invalid"
        if corruption.startswith("occurrence_")
        else "stored occurrence link is invalid"
    )
    assert str(captured.value) == expected
    assert captured.value.__cause__ is None
    assert "RAW_BODY_SECRET" not in str(captured.value)
    assert "f" * 64 not in str(captured.value)


@pytest.mark.parametrize(
    ("method", "kwargs"),
    (
        ("links", {"limit": True}),
        ("links", {"limit": 0}),
        ("links", {"limit": 501}),
        ("links", {"review_statuses": []}),
        ("links", {"review_statuses": ()}),
        ("links", {"review_statuses": ("REVIEW",)}),
        ("links", {"review_statuses": (ReviewStatus.REVIEW, ReviewStatus.REVIEW)}),
        ("links", {"include_stale": 1}),
        ("subject", {"include_source_changed": 0}),
        ("subject", {"occurrence_review_statuses": ()}),
    ),
)
def test_all_list_inputs_validate_before_database_access(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    method: str,
    kwargs: dict[str, object],
) -> None:
    fixture = _fixture(tmp_path, subject_count=1)
    repository = OccurrenceRepository(fixture.project)

    def forbidden_connect(database: Database) -> sqlite3.Connection:
        raise AssertionError("invalid input reached database")

    monkeypatch.setattr(Database, "connect", forbidden_connect)
    with pytest.raises(ValueError):
        if method == "links":
            repository.list_links_for_occurrence(new_id(), **kwargs)  # type: ignore[arg-type]
        else:
            repository.list_subject_occurrences(new_id(), **kwargs)  # type: ignore[arg-type]


def test_list_record_ids_validate_before_database_access(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fixture = _fixture(tmp_path, subject_count=1)
    repository = OccurrenceRepository(fixture.project)

    def forbidden_connect(database: Database) -> sqlite3.Connection:
        raise AssertionError("invalid input reached database")

    monkeypatch.setattr(Database, "connect", forbidden_connect)
    with pytest.raises(ValueError, match="occurrence record ID is invalid"):
        repository.list_links_for_occurrence("not-a-uuid")
    with pytest.raises(ValueError, match="occurrence subject ID is invalid"):
        repository.list_subject_occurrences("not-a-uuid")


def test_subject_list_uses_fixed_bounded_query_count(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fixture = _fixture(tmp_path, subject_count=1)
    occurrences, links = _batch_for_subject(fixture, 100)
    _persist(fixture, occurrences, links)
    statements: list[str] = []
    original_connect = Database.connect

    def traced_connect(database: Database) -> sqlite3.Connection:
        connection = original_connect(database)
        connection.set_trace_callback(statements.append)
        return connection

    monkeypatch.setattr(Database, "connect", traced_connect)
    records = OccurrenceRepository(fixture.project).list_subject_occurrences(
        fixture.subject_ids[0],
        limit=100,
    )
    select_count = sum(
        statement.lstrip().upper().startswith("SELECT") for statement in statements
    )

    assert len(records) == 100
    assert select_count <= 8


def test_read_errors_are_sanitized_and_base_exception_propagates(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fixture = _fixture(tmp_path)
    repository = OccurrenceRepository(fixture.project)

    def sqlite_failure(database: Database) -> NoReturn:
        raise sqlite3.OperationalError("RAW SQL SECRET")

    monkeypatch.setattr(Database, "connect", sqlite_failure)
    with pytest.raises(OccurrenceRepositoryError) as captured:
        repository.get_occurrence(new_id())
    assert str(captured.value) == "occurrence records could not be read"
    assert captured.value.__cause__ is None
    assert "RAW SQL SECRET" not in str(captured.value)

    def stop(database: Database) -> NoReturn:
        raise KeyboardInterrupt

    monkeypatch.setattr(Database, "connect", stop)
    with pytest.raises(KeyboardInterrupt):
        repository.get_occurrence(new_id())
