from __future__ import annotations

import hashlib
import sqlite3
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import NoReturn

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

CONTENT = "序章\r\n\r\n艾琳发现钥匙🔑。\r\n守卫随后封锁现场。"
NOW = datetime(2026, 8, 14, 8, 0, tzinfo=UTC)


def _hash(content: str) -> str:
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


@dataclass(frozen=True, slots=True)
class Fixture:
    project: ProjectRepository
    chapter_id: str
    revision: int
    source_hash: str
    narrative_sequence: int
    first_subject_id: str
    second_subject_id: str


def _fixture(tmp_path: Path, *, content: str = CONTENT) -> Fixture:
    project = ProjectRepository.create(tmp_path / "project", "Occurrence repository")
    chapter = ChapterRepository(project).create_chapter(
        project.list_volumes()[0].id,
        "发现",
        content=content,
    )
    characters = CharacterMemoryRepository(project)
    first = characters.create_character("艾琳")
    second = characters.create_character("守卫")
    return Fixture(
        project=project,
        chapter_id=chapter.id,
        revision=chapter.revision,
        source_hash=_hash(content),
        narrative_sequence=1,
        first_subject_id=first.id,
        second_subject_id=second.id,
    )


def _occurrence(
    fixture: Fixture,
    *,
    ordinal: int = 0,
    occurrence_id: str | None = None,
    candidate_source_id: str | None = None,
    source_start: int | None = None,
    source_end: int | None = None,
) -> Occurrence:
    start = CONTENT.index("艾琳") if source_start is None else source_start
    end = CONTENT.index("。", start) + 1 if source_end is None else source_end
    return Occurrence(
        id=occurrence_id or new_id(),
        candidate_source_id=(
            candidate_source_id
            or f"semantic-window:{fixture.chapter_id}:occurrence:{ordinal}"
        ),
        type_code=OccurrenceType.DISCOVERY,
        vocabulary_version=OCCURRENCE_TYPE_VOCABULARY_V1,
        title="发现钥匙",
        summary="艾琳发现了带有标记的钥匙。",
        narrative_sequence=fixture.narrative_sequence,
        authority=Authority.MODEL_EXTRACTED,
        review_status=ReviewStatus.REVIEW,
        source_type=SourceType.MODEL,
        stale=False,
        source_changed=False,
        source_ranges=(
            OccurrenceSourceRange(
                ordinal=0,
                source_chapter_id=fixture.chapter_id,
                source_revision=fixture.revision,
                source_hash=fixture.source_hash,
                semantic_window_source_id=(
                    f"semantic-window:{fixture.chapter_id}:{ordinal}"
                ),
                policy_version="semantic-window-v1",
                source_start=start,
                source_end=end,
            ),
        ),
        created_at=NOW,
        updated_at=NOW,
    )


def _link(
    fixture: Fixture,
    occurrence: Occurrence,
    *,
    ordinal: int = 0,
    subject_id: str | None = None,
    link_id: str | None = None,
    candidate_source_id: str | None = None,
) -> SubjectOccurrenceLink:
    start = CONTENT.index("艾琳")
    return SubjectOccurrenceLink(
        id=link_id or new_id(),
        candidate_source_id=(
            candidate_source_id
            or f"semantic-window:{fixture.chapter_id}:participant-link:{ordinal}"
        ),
        occurrence_id=occurrence.id,
        subject_id=subject_id or fixture.first_subject_id,
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
                source_chapter_id=fixture.chapter_id,
                source_revision=fixture.revision,
                source_hash=fixture.source_hash,
                semantic_window_source_id=(
                    f"semantic-window:{fixture.chapter_id}:{ordinal}"
                ),
                policy_version="semantic-window-v1",
                source_start=start,
                source_end=start + len("艾琳"),
            ),
        ),
        created_at=NOW,
        updated_at=NOW,
    )


def _create(
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


def _rows(project: ProjectRepository, table: str) -> tuple[tuple[object, ...], ...]:
    with project.database.connect() as connection:
        values = connection.execute(f"SELECT * FROM {table} ORDER BY rowid").fetchall()
    return tuple(tuple(row) for row in values)


def _occurrence_rows(project: ProjectRepository) -> dict[str, tuple[object, ...]]:
    return {
        table: _rows(project, table)
        for table in (
            "occurrences",
            "occurrence_source_ranges",
            "subject_occurrence_links",
            "subject_occurrence_link_source_ranges",
            "memory_dependencies",
        )
    }


def test_create_model_candidates_persists_exact_crlf_unicode_ranges_and_dependencies(
    tmp_path: Path,
) -> None:
    fixture = _fixture(tmp_path)
    occurrence = _occurrence(fixture)
    first = _link(fixture, occurrence)
    second = _link(
        fixture,
        occurrence,
        ordinal=1,
        subject_id=fixture.second_subject_id,
    )

    _create(fixture, (occurrence,), (first, second))

    with fixture.project.database.connect() as connection:
        stored_occurrence = connection.execute(
            "SELECT * FROM occurrences WHERE id = ?",
            (occurrence.id,),
        ).fetchone()
        occurrence_range = connection.execute(
            "SELECT * FROM occurrence_source_ranges WHERE occurrence_id = ?",
            (occurrence.id,),
        ).fetchone()
        stored_links = connection.execute(
            "SELECT * FROM subject_occurrence_links ORDER BY candidate_source_id"
        ).fetchall()
        dependencies = connection.execute(
            """
            SELECT memory_type, memory_id, source_chapter_id,
                   source_revision, source_hash, status
            FROM memory_dependencies
            WHERE memory_type IN ('OCCURRENCE', 'SUBJECT_OCCURRENCE_LINK')
            ORDER BY memory_type, memory_id
            """
        ).fetchall()

    assert stored_occurrence["candidate_source_id"] == occurrence.candidate_source_id
    assert stored_occurrence["review_status"] == "REVIEW"
    assert tuple(occurrence_range)[1:] == (
        0,
        fixture.chapter_id,
        fixture.revision,
        fixture.source_hash,
        occurrence.source_ranges[0].semantic_window_source_id,
        "semantic-window-v1",
        occurrence.source_ranges[0].source_start,
        occurrence.source_ranges[0].source_end,
    )
    assert CONTENT[
        int(occurrence_range["source_start"]) : int(occurrence_range["source_end"])
    ] == "艾琳发现钥匙🔑。"
    assert {row["subject_id"] for row in stored_links} == {
        fixture.first_subject_id,
        fixture.second_subject_id,
    }
    assert {
        (row["memory_type"], row["memory_id"], row["status"])
        for row in dependencies
    } == {
        ("OCCURRENCE", occurrence.id, "CURRENT"),
        ("SUBJECT_OCCURRENCE_LINK", first.id, "CURRENT"),
        ("SUBJECT_OCCURRENCE_LINK", second.id, "CURRENT"),
    }
    assert all(
        row["source_chapter_id"] == fixture.chapter_id
        and row["source_revision"] == fixture.revision
        and row["source_hash"] == fixture.source_hash
        for row in dependencies
    )


def test_narrative_sequence_uses_canonical_cross_volume_order(tmp_path: Path) -> None:
    project = ProjectRepository.create(tmp_path / "project", "Book order")
    chapters = ChapterRepository(project)
    first_volume = project.list_volumes()[0]
    chapters.create_chapter(first_volume.id, "Earlier", content="earlier")
    second_volume = project.create_volume("Second")
    chapter = chapters.create_chapter(second_volume.id, "Target", content=CONTENT)
    characters = CharacterMemoryRepository(project)
    first = characters.create_character("艾琳")
    second = characters.create_character("守卫")
    fixture = Fixture(
        project,
        chapter.id,
        chapter.revision,
        _hash(CONTENT),
        2,
        first.id,
        second.id,
    )
    occurrence = _occurrence(fixture)

    _create(fixture, (occurrence,), ())

    with project.database.connect() as connection:
        stored = connection.execute(
            "SELECT narrative_sequence FROM occurrences WHERE id = ?",
            (occurrence.id,),
        ).fetchone()
    assert stored["narrative_sequence"] == 2


def test_noncanonical_narrative_sequence_is_rejected_before_write(
    tmp_path: Path,
) -> None:
    fixture = _fixture(tmp_path)

    with pytest.raises(ValueError, match="occurrence narrative sequence is invalid"):
        _create(
            fixture,
            (replace(_occurrence(fixture), narrative_sequence=2),),
            (),
        )

    assert _rows(fixture.project, "occurrences") == ()


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("review_status", ReviewStatus.APPROVED),
        ("review_status", ReviewStatus.REJECTED),
        ("review_status", ReviewStatus.LOCKED),
        ("stale", True),
        ("source_changed", True),
    ],
)
def test_create_boundary_accepts_only_fresh_review_occurrences(
    tmp_path: Path,
    field: str,
    value: object,
) -> None:
    fixture = _fixture(tmp_path)
    occurrence = replace(_occurrence(fixture), **{field: value})

    with pytest.raises(ValueError, match="occurrence create contract is invalid"):
        _create(fixture, (occurrence,), ())

    assert _rows(fixture.project, "occurrences") == ()


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("review_status", ReviewStatus.APPROVED),
        ("review_status", ReviewStatus.REJECTED),
        ("review_status", ReviewStatus.LOCKED),
        ("stale", True),
        ("source_changed", True),
    ],
)
def test_create_boundary_accepts_only_fresh_review_links(
    tmp_path: Path,
    field: str,
    value: object,
) -> None:
    fixture = _fixture(tmp_path)
    occurrence = _occurrence(fixture)
    link = replace(_link(fixture, occurrence), **{field: value})

    with pytest.raises(ValueError, match="occurrence create contract is invalid"):
        _create(fixture, (occurrence,), (link,))

    assert _rows(fixture.project, "occurrences") == ()


@pytest.mark.parametrize("state", ("missing", "inactive"))
def test_links_require_existing_active_character_subjects(
    tmp_path: Path,
    state: str,
) -> None:
    fixture = _fixture(tmp_path)
    occurrence = _occurrence(fixture)
    subject_id = new_id()
    if state == "inactive":
        subject_id = fixture.first_subject_id
        with fixture.project.database.connect() as connection, connection:
            connection.execute(
                "UPDATE subjects SET active = 0 WHERE id = ?",
                (subject_id,),
            )
    before_subjects = _rows(fixture.project, "subjects")
    link = _link(fixture, occurrence, subject_id=subject_id)

    with pytest.raises(OccurrenceRepositoryError) as captured:
        _create(fixture, (occurrence,), (link,))

    assert str(captured.value) == "occurrence candidate subject is unavailable"
    assert _rows(fixture.project, "subjects") == before_subjects
    assert _rows(fixture.project, "occurrences") == ()


def test_subject_schema_and_repository_do_not_create_event_subjects(tmp_path: Path) -> None:
    fixture = _fixture(tmp_path)
    occurrence = _occurrence(fixture)
    fake_subject_id = new_id()
    with fixture.project.database.connect() as connection, connection:
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute(
                """
                INSERT INTO subjects (
                    id, type, canonical_name, active, created_at, updated_at
                ) VALUES (?, 'EVENT', 'Not a Character', 1, ?, ?)
                """,
                (fake_subject_id, NOW.isoformat(), NOW.isoformat()),
            )

    with pytest.raises(OccurrenceRepositoryError):
        _create(
            fixture,
            (occurrence,),
            (_link(fixture, occurrence, subject_id=fake_subject_id),),
        )
    assert len(_rows(fixture.project, "subjects")) == 2


@pytest.mark.parametrize(
    "failure",
    ("revision", "hash", "deleted", "tamper", "path", "database"),
)
def test_source_identity_and_manuscript_containment_fail_closed(
    tmp_path: Path,
    failure: str,
) -> None:
    fixture = _fixture(tmp_path)
    expected_revision = fixture.revision
    expected_hash = fixture.source_hash
    with fixture.project.database.connect() as connection:
        path = fixture.project.layout.root / str(
            connection.execute(
                "SELECT content_path FROM chapters WHERE id = ?",
                (fixture.chapter_id,),
            ).fetchone()["content_path"]
        )
    if failure == "revision":
        expected_revision += 1
    elif failure == "hash":
        expected_hash = "f" * 64
    elif failure == "deleted":
        with fixture.project.database.connect() as connection, connection:
            connection.execute(
                "UPDATE chapters SET is_deleted = 1 WHERE id = ?",
                (fixture.chapter_id,),
            )
    elif failure == "tamper":
        with path.open("w", encoding="utf-8", newline="") as stream:
            stream.write("tampered secret manuscript")
    elif failure == "path":
        outside = fixture.project.layout.root / "assets" / "outside.md"
        outside.parent.mkdir(parents=True, exist_ok=True)
        with outside.open("w", encoding="utf-8", newline="") as stream:
            stream.write(CONTENT)
        with fixture.project.database.connect() as connection, connection:
            connection.execute(
                "UPDATE chapters SET content_path = ? WHERE id = ?",
                (
                    outside.relative_to(fixture.project.layout.root).as_posix(),
                    fixture.chapter_id,
                ),
            )
    else:
        with fixture.project.database.connect() as connection, connection:
            connection.execute(
                "UPDATE chapters SET revision = 'RAW_DB_SECRET' WHERE id = ?",
                (fixture.chapter_id,),
            )

    with pytest.raises(OccurrenceRepositoryError) as captured:
        OccurrenceRepository(
            fixture.project
        ).create_model_candidates_for_chapter(
            fixture.chapter_id,
            expected_revision=expected_revision,
            expected_source_hash=expected_hash,
            occurrences=(_occurrence(fixture),),
            links=(),
        )

    assert str(captured.value) == "occurrence candidate source is unavailable"
    assert _rows(fixture.project, "occurrences") == ()
    assert "tampered" not in str(captured.value)
    assert str(fixture.project.layout.root) not in str(captured.value)
    assert fixture.source_hash not in str(captured.value)


def test_range_must_fit_exact_current_source(tmp_path: Path) -> None:
    fixture = _fixture(tmp_path)
    occurrence = _occurrence(
        fixture,
        source_start=len(CONTENT) - 1,
        source_end=len(CONTENT) + 1,
    )

    with pytest.raises(ValueError, match="occurrence source range is outside source"):
        _create(fixture, (occurrence,), ())

    assert _rows(fixture.project, "occurrences") == ()


@pytest.mark.parametrize("field", ("source_chapter_id", "source_revision", "source_hash"))
def test_ranges_must_match_exact_source_identity(
    tmp_path: Path,
    field: str,
) -> None:
    fixture = _fixture(tmp_path)
    occurrence = _occurrence(fixture)
    source_range = occurrence.source_ranges[0]
    value: object
    if field == "source_chapter_id":
        value = new_id()
    elif field == "source_revision":
        value = fixture.revision + 1
    else:
        value = "f" * 64
    changed = replace(
        occurrence,
        source_ranges=(replace(source_range, **{field: value}),),
    )

    with pytest.raises(ValueError, match="occurrence source range is outside source"):
        _create(fixture, (changed,), ())

    assert _rows(fixture.project, "occurrences") == ()


def test_source_change_between_pre_and_post_validation_rolls_back(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fixture = _fixture(tmp_path)
    repository = OccurrenceRepository(fixture.project)
    original = repository._current_source
    calls = 0

    def race(*args: object, **kwargs: object) -> object:
        nonlocal calls
        calls += 1
        if calls == 2:
            with fixture.project.database.connect() as connection:
                path = fixture.project.layout.root / str(
                    connection.execute(
                        "SELECT content_path FROM chapters WHERE id = ?",
                        (fixture.chapter_id,),
                    ).fetchone()["content_path"]
                )
            with path.open("w", encoding="utf-8", newline="") as stream:
                stream.write("newer content")
        return original(*args, **kwargs)

    monkeypatch.setattr(repository, "_current_source", race)

    with pytest.raises(OccurrenceRepositoryError):
        repository.create_model_candidates_for_chapter(
            fixture.chapter_id,
            expected_revision=fixture.revision,
            expected_source_hash=fixture.source_hash,
            occurrences=(_occurrence(fixture),),
            links=(),
        )

    assert calls == 2
    assert _rows(fixture.project, "occurrences") == ()
    assert _rows(fixture.project, "memory_dependencies") == ()


def test_exact_replay_is_noop_and_mixed_replay_plus_new_is_atomic(
    tmp_path: Path,
) -> None:
    fixture = _fixture(tmp_path)
    first = _occurrence(fixture)
    first_link = _link(fixture, first)
    _create(fixture, (first,), (first_link,))
    after_first = _occurrence_rows(fixture.project)

    _create(fixture, (first,), (first_link,))

    assert _occurrence_rows(fixture.project) == after_first

    second = _occurrence(fixture, ordinal=1)
    second_link = _link(
        fixture,
        second,
        ordinal=1,
        subject_id=fixture.second_subject_id,
    )
    _create(fixture, (first, second), (first_link, second_link))
    after_mixed = _occurrence_rows(fixture.project)

    assert after_mixed["occurrences"][:1] == after_first["occurrences"]
    assert after_mixed["memory_dependencies"][:2] == after_first[
        "memory_dependencies"
    ]
    assert len(after_mixed["occurrences"]) == 2
    assert len(after_mixed["subject_occurrence_links"]) == 2
    assert len(after_mixed["memory_dependencies"]) == 4


def test_rebuilt_dtos_with_later_timestamps_replay_as_storage_noop(
    tmp_path: Path,
) -> None:
    fixture = _fixture(tmp_path)
    occurrence = _occurrence(fixture)
    link = _link(fixture, occurrence)
    _create(fixture, (occurrence,), (link,))
    first_snapshot = _occurrence_rows(fixture.project)
    later = NOW + timedelta(days=1)

    _create(
        fixture,
        (
            replace(
                occurrence,
                created_at=later,
                updated_at=later + timedelta(minutes=1),
            ),
        ),
        (
            replace(
                link,
                created_at=later,
                updated_at=later + timedelta(minutes=1),
            ),
        ),
    )

    assert _occurrence_rows(fixture.project) == first_snapshot


@pytest.mark.parametrize("record", ("occurrence", "link"))
@pytest.mark.parametrize("corruption", ("malformed", "naive", "reversed"))
def test_replay_rejects_invalid_storage_owned_timestamps_without_mutation(
    tmp_path: Path,
    record: str,
    corruption: str,
) -> None:
    fixture = _fixture(tmp_path)
    occurrence = _occurrence(fixture)
    link = _link(fixture, occurrence)
    _create(fixture, (occurrence,), (link,))
    table = "occurrences" if record == "occurrence" else "subject_occurrence_links"
    record_id = occurrence.id if record == "occurrence" else link.id
    if corruption == "malformed":
        created_at = "RAW_TIMESTAMP_SECRET"
        updated_at = NOW.isoformat()
    elif corruption == "naive":
        created_at = "2026-08-14T08:00:00"
        updated_at = "2026-08-14T09:00:00"
    else:
        created_at = (NOW + timedelta(minutes=1)).isoformat()
        updated_at = NOW.isoformat()
    with fixture.project.database.connect() as connection, connection:
        connection.execute(
            f"UPDATE {table} SET created_at = ?, updated_at = ? WHERE id = ?",
            (created_at, updated_at, record_id),
        )
    corrupted_snapshot = _occurrence_rows(fixture.project)

    with pytest.raises(OccurrenceRepositoryError) as captured:
        _create(fixture, (occurrence,), (link,))

    assert str(captured.value) == "occurrence candidate replay conflicts with storage"
    assert "RAW_TIMESTAMP_SECRET" not in str(captured.value)
    assert _occurrence_rows(fixture.project) == corrupted_snapshot


@pytest.mark.parametrize("identity", ("record_id", "candidate_source_id"))
def test_persisted_occurrence_identity_cannot_be_reused_by_later_link(
    tmp_path: Path,
    identity: str,
) -> None:
    fixture = _fixture(tmp_path)
    first = _occurrence(fixture)
    _create(fixture, (first,), ())
    first_snapshot = _occurrence_rows(fixture.project)
    second = _occurrence(fixture, ordinal=1)
    second_link = _link(
        fixture,
        second,
        ordinal=1,
        subject_id=fixture.second_subject_id,
    )
    if identity == "record_id":
        second_link = replace(second_link, id=first.id)
    else:
        second_link = replace(
            second_link,
            candidate_source_id=first.candidate_source_id,
        )

    with pytest.raises(OccurrenceRepositoryError, match="replay conflicts"):
        _create(fixture, (second,), (second_link,))

    assert _occurrence_rows(fixture.project) == first_snapshot


@pytest.mark.parametrize("identity", ("record_id", "candidate_source_id"))
def test_persisted_link_identity_cannot_be_reused_by_later_occurrence(
    tmp_path: Path,
    identity: str,
) -> None:
    fixture = _fixture(tmp_path)
    first = _occurrence(fixture)
    first_link = _link(fixture, first)
    _create(fixture, (first,), (first_link,))
    first_snapshot = _occurrence_rows(fixture.project)
    second = _occurrence(fixture, ordinal=1)
    if identity == "record_id":
        second = replace(second, id=first_link.id)
    else:
        second = replace(
            second,
            candidate_source_id=first_link.candidate_source_id,
        )

    with pytest.raises(OccurrenceRepositoryError, match="replay conflicts"):
        _create(fixture, (second,), ())

    assert _occurrence_rows(fixture.project) == first_snapshot


@pytest.mark.parametrize(
    ("record", "field", "value"),
    [
        ("occurrence", "title", "不同标题"),
        ("occurrence", "type_code", OccurrenceType.ACTION),
        ("occurrence", "summary", "不同摘要"),
        ("link", "role", "旁观者"),
    ],
)
def test_same_candidate_identity_with_changed_scalar_conflicts_atomically(
    tmp_path: Path,
    record: str,
    field: str,
    value: object,
) -> None:
    fixture = _fixture(tmp_path)
    first = _occurrence(fixture)
    link = _link(fixture, first)
    _create(fixture, (first,), (link,))
    before = _occurrence_rows(fixture.project)
    second = _occurrence(fixture, ordinal=1)
    occurrences = (first, second)
    links = (link,)
    if record == "occurrence":
        occurrences = (replace(first, **{field: value}), second)
    else:
        links = (replace(link, **{field: value}),)

    with pytest.raises(
        OccurrenceRepositoryError,
        match="occurrence candidate replay conflicts with storage",
    ):
        _create(fixture, occurrences, links)

    assert _occurrence_rows(fixture.project) == before


def test_same_link_candidate_with_changed_subject_conflicts(tmp_path: Path) -> None:
    fixture = _fixture(tmp_path)
    occurrence = _occurrence(fixture)
    link = _link(fixture, occurrence)
    _create(fixture, (occurrence,), (link,))
    before = _occurrence_rows(fixture.project)

    with pytest.raises(OccurrenceRepositoryError, match="replay conflicts"):
        _create(
            fixture,
            (occurrence,),
            (replace(link, subject_id=fixture.second_subject_id),),
        )

    assert _occurrence_rows(fixture.project) == before


def test_same_link_candidate_with_changed_occurrence_reference_conflicts(
    tmp_path: Path,
) -> None:
    fixture = _fixture(tmp_path)
    first = _occurrence(fixture)
    first_link = _link(fixture, first)
    _create(fixture, (first,), (first_link,))
    before = _occurrence_rows(fixture.project)
    second = _occurrence(fixture, ordinal=1)

    with pytest.raises(OccurrenceRepositoryError, match="replay conflicts"):
        _create(
            fixture,
            (first, second),
            (replace(first_link, occurrence_id=second.id),),
        )

    assert _occurrence_rows(fixture.project) == before


@pytest.mark.parametrize(
    "corruption",
    ("missing_range", "extra_range", "dependency", "narrative_sequence"),
)
def test_replay_rejects_missing_extra_range_or_dependency_corruption(
    tmp_path: Path,
    corruption: str,
) -> None:
    fixture = _fixture(tmp_path)
    occurrence = _occurrence(fixture)
    _create(fixture, (occurrence,), ())
    with fixture.project.database.connect() as connection, connection:
        if corruption == "missing_range":
            connection.execute(
                "DELETE FROM occurrence_source_ranges WHERE occurrence_id = ?",
                (occurrence.id,),
            )
        elif corruption == "extra_range":
            source = occurrence.source_ranges[0]
            connection.execute(
                """
                INSERT INTO occurrence_source_ranges (
                    occurrence_id, ordinal, source_chapter_id, source_revision,
                    source_hash, semantic_window_source_id, policy_version,
                    source_start, source_end
                ) VALUES (?, 1, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    occurrence.id,
                    source.source_chapter_id,
                    source.source_revision,
                    source.source_hash,
                    source.semantic_window_source_id,
                    source.policy_version,
                    source.source_start + 1,
                    source.source_end,
                ),
            )
        elif corruption == "dependency":
            connection.execute(
                """
                UPDATE memory_dependencies SET status = 'STALE'
                WHERE memory_type = 'OCCURRENCE' AND memory_id = ?
                """,
                (occurrence.id,),
            )
        else:
            connection.execute(
                "UPDATE occurrences SET narrative_sequence = 2 WHERE id = ?",
                (occurrence.id,),
            )
    before = _occurrence_rows(fixture.project)

    with pytest.raises(OccurrenceRepositoryError, match="replay conflicts"):
        _create(fixture, (occurrence,), ())

    assert _occurrence_rows(fixture.project) == before


@pytest.mark.parametrize("corruption", ("missing_range", "extra_range", "dependency"))
def test_link_replay_rejects_range_or_dependency_corruption(
    tmp_path: Path,
    corruption: str,
) -> None:
    fixture = _fixture(tmp_path)
    occurrence = _occurrence(fixture)
    link = _link(fixture, occurrence)
    _create(fixture, (occurrence,), (link,))
    with fixture.project.database.connect() as connection, connection:
        if corruption == "missing_range":
            connection.execute(
                "DELETE FROM subject_occurrence_link_source_ranges WHERE link_id = ?",
                (link.id,),
            )
        elif corruption == "extra_range":
            source = link.source_ranges[0]
            connection.execute(
                """
                INSERT INTO subject_occurrence_link_source_ranges (
                    link_id, ordinal, source_chapter_id, source_revision,
                    source_hash, semantic_window_source_id, policy_version,
                    source_start, source_end
                ) VALUES (?, 1, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    link.id,
                    source.source_chapter_id,
                    source.source_revision,
                    source.source_hash,
                    source.semantic_window_source_id,
                    source.policy_version,
                    source.source_start,
                    source.source_end + 1,
                ),
            )
        else:
            connection.execute(
                """
                UPDATE memory_dependencies SET status = 'STALE'
                WHERE memory_type = 'SUBJECT_OCCURRENCE_LINK' AND memory_id = ?
                """,
                (link.id,),
            )
    before = _occurrence_rows(fixture.project)

    with pytest.raises(OccurrenceRepositoryError, match="replay conflicts"):
        _create(fixture, (occurrence,), (link,))

    assert _occurrence_rows(fixture.project) == before


def test_same_candidate_with_changed_range_conflicts(tmp_path: Path) -> None:
    fixture = _fixture(tmp_path)
    occurrence = _occurrence(fixture)
    _create(fixture, (occurrence,), ())
    before = _occurrence_rows(fixture.project)
    source = occurrence.source_ranges[0]
    changed = replace(
        occurrence,
        source_ranges=(
            replace(
                source,
                source_start=source.source_start + 1,
            ),
        ),
    )

    with pytest.raises(OccurrenceRepositoryError, match="replay conflicts"):
        _create(fixture, (changed,), ())

    assert _occurrence_rows(fixture.project) == before


@pytest.mark.parametrize(
    "bad_input",
    (
        "occurrence_id",
        "occurrence_candidate",
        "link_id",
        "link_candidate",
        "cross_record_id",
        "cross_candidate",
        "pair",
        "dangling",
        "links_without_occurrences",
    ),
)
def test_batch_shape_duplicates_and_dangling_links_are_rejected(
    tmp_path: Path,
    bad_input: str,
) -> None:
    fixture = _fixture(tmp_path)
    first = _occurrence(fixture)
    second = _occurrence(fixture, ordinal=1)
    first_link = _link(fixture, first)
    second_link = _link(
        fixture,
        first,
        ordinal=1,
        subject_id=fixture.second_subject_id,
    )
    occurrences: tuple[Occurrence, ...] = (first, second)
    links: tuple[SubjectOccurrenceLink, ...] = (first_link, second_link)
    if bad_input == "occurrence_id":
        occurrences = (first, replace(second, id=first.id))
    elif bad_input == "occurrence_candidate":
        occurrences = (
            first,
            replace(second, candidate_source_id=first.candidate_source_id),
        )
    elif bad_input == "link_id":
        links = (first_link, replace(second_link, id=first_link.id))
    elif bad_input == "link_candidate":
        links = (
            first_link,
            replace(
                second_link,
                candidate_source_id=first_link.candidate_source_id,
            ),
        )
    elif bad_input == "cross_record_id":
        links = (replace(first_link, id=first.id),)
    elif bad_input == "cross_candidate":
        links = (
            replace(
                first_link,
                candidate_source_id=first.candidate_source_id,
            ),
        )
    elif bad_input == "pair":
        links = (
            first_link,
            replace(
                second_link,
                subject_id=first_link.subject_id,
            ),
        )
    elif bad_input == "dangling":
        links = (replace(first_link, occurrence_id=new_id()),)
    else:
        occurrences = ()
        links = (first_link,)

    with pytest.raises(ValueError, match="occurrence candidate batch is invalid"):
        _create(fixture, occurrences, links)

    assert _rows(fixture.project, "occurrences") == ()


def test_batch_requires_tuples_and_enforces_caps(tmp_path: Path) -> None:
    fixture = _fixture(tmp_path)
    occurrence = _occurrence(fixture)
    repository = OccurrenceRepository(fixture.project)
    with pytest.raises(ValueError, match="occurrence candidate batch is invalid"):
        repository.create_model_candidates_for_chapter(
            fixture.chapter_id,
            expected_revision=fixture.revision,
            expected_source_hash=fixture.source_hash,
            occurrences=[occurrence],  # type: ignore[arg-type]
            links=(),
        )
    too_many_occurrences = tuple(
        _occurrence(fixture, ordinal=index) for index in range(101)
    )
    with pytest.raises(ValueError, match="occurrence candidate batch is invalid"):
        _create(fixture, too_many_occurrences, ())
    link = _link(fixture, occurrence)
    too_many_links = tuple(
        replace(
            link,
            id=new_id(),
            candidate_source_id=f"{link.candidate_source_id}:{index}",
        )
        for index in range(501)
    )
    with pytest.raises(ValueError, match="occurrence candidate batch is invalid"):
        _create(fixture, (occurrence,), too_many_links)


def test_empty_batch_is_source_validated_noop_and_links_only_is_invalid(
    tmp_path: Path,
) -> None:
    fixture = _fixture(tmp_path)
    repository = OccurrenceRepository(fixture.project)

    assert (
        repository.create_model_candidates_for_chapter(
            fixture.chapter_id,
            expected_revision=fixture.revision,
            expected_source_hash=fixture.source_hash,
            occurrences=(),
            links=(),
        )
        is None
    )
    occurrence = _occurrence(fixture)
    with pytest.raises(ValueError, match="occurrence candidate batch is invalid"):
        _create(fixture, (), (_link(fixture, occurrence),))

    assert _occurrence_rows(fixture.project)["occurrences"] == ()


@pytest.mark.parametrize(
    "table",
    (
        "occurrences",
        "occurrence_source_ranges",
        "subject_occurrence_links",
        "subject_occurrence_link_source_ranges",
        "memory_dependencies",
    ),
)
def test_failure_at_each_write_layer_rolls_back_the_whole_batch(
    tmp_path: Path,
    table: str,
) -> None:
    fixture = _fixture(tmp_path)
    occurrence = _occurrence(fixture)
    link = _link(fixture, occurrence)
    marker = "RAW_SQL_TRIGGER_SECRET"
    with fixture.project.database.connect() as connection, connection:
        connection.execute(
            f"""
            CREATE TRIGGER fail_{table}_insert
            BEFORE INSERT ON {table}
            BEGIN
                SELECT RAISE(ABORT, '{marker}');
            END
            """
        )

    with pytest.raises(OccurrenceRepositoryError) as captured:
        _create(fixture, (occurrence,), (link,))

    assert str(captured.value) == "occurrence candidate batch could not be saved"
    assert captured.value.__cause__ is None
    assert marker not in str(captured.value)
    assert _rows(fixture.project, "occurrences") == ()
    assert _rows(fixture.project, "occurrence_source_ranges") == ()
    assert _rows(fixture.project, "subject_occurrence_links") == ()
    assert _rows(fixture.project, "subject_occurrence_link_source_ranges") == ()
    assert _rows(fixture.project, "memory_dependencies") == ()


def test_base_exception_is_not_swallowed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fixture = _fixture(tmp_path)
    repository = OccurrenceRepository(fixture.project)

    def stop(*args: object, **kwargs: object) -> NoReturn:
        raise KeyboardInterrupt

    monkeypatch.setattr(repository, "_current_source", stop)

    with pytest.raises(KeyboardInterrupt):
        repository.create_model_candidates_for_chapter(
            fixture.chapter_id,
            expected_revision=fixture.revision,
            expected_source_hash=fixture.source_hash,
            occurrences=(),
            links=(),
        )


def test_create_does_not_modify_existing_subject_state_view_or_search_rows(
    tmp_path: Path,
) -> None:
    fixture = _fixture(tmp_path)
    occurrence = _occurrence(fixture)
    before = {
        table: _rows(fixture.project, table)
        for table in (
            "subjects",
            "characters",
            "character_state_events",
            "view_assertions",
            "memory_documents",
        )
    }

    _create(
        fixture,
        (occurrence,),
        (_link(fixture, occurrence),),
    )

    after = {table: _rows(fixture.project, table) for table in before}
    assert after == before
