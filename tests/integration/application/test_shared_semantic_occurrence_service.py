from __future__ import annotations

import hashlib
import sqlite3
from dataclasses import dataclass, fields, replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import NoReturn

import pytest

from ai_novel_studio.application.shared_semantic_import_service import (
    SharedSemanticChapterResult,
)
from ai_novel_studio.application.shared_semantic_occurrence_service import (
    OccurrenceBindingFailure,
    OccurrenceBindingFailureCode,
    OccurrenceBindingIssue,
    OccurrenceBindingIssueCode,
    OccurrenceBindingStatus,
    OccurrenceChapterBindingResult,
    SharedSemanticOccurrenceService,
)
from ai_novel_studio.core.context.semantic_windowing import (
    SemanticWindow,
    SemanticWindowPolicy,
    project_semantic_windows,
)
from ai_novel_studio.core.context.shared_semantic_result import (
    AliasCandidate,
    OccurrenceCandidate,
    ParticipantLinkCandidate,
    ResolvedSubjectReference,
    SharedSemanticResult,
    SourceSpan,
    StateChangeCandidate,
    SubjectMentionCandidate,
    ViewDifferenceCandidate,
    WindowSummaryCandidate,
    candidate_source_id,
)
from ai_novel_studio.domain.identifiers import new_id
from ai_novel_studio.domain.memory import ReviewStatus
from ai_novel_studio.domain.view import ViewType
from ai_novel_studio.infrastructure.storage.chapter_repository import ChapterRepository
from ai_novel_studio.infrastructure.storage.character_memory_repository import (
    CharacterMemoryRepository,
)
from ai_novel_studio.infrastructure.storage.occurrence_repository import (
    OccurrenceRepository,
    OccurrenceRepositoryError,
)
from ai_novel_studio.infrastructure.storage.project_repository import ProjectRepository
from ai_novel_studio.infrastructure.storage.subject_repository import SubjectRepository

_FIXED_CHAPTER_ID = "00000000-0000-0000-0000-000000000001"
_NOW = datetime(2026, 8, 21, 8, 0, tzinfo=UTC)
_EXPECTED_OCCURRENCE_ID = "0e84dc2c-d7ac-5540-8491-83e7a9c48e73"
_EXPECTED_LINK_ID = "8fe01a6a-5e68-5637-b9d2-6d3328d20303"


def _hash(content: str) -> str:
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


@dataclass(frozen=True, slots=True)
class Fixture:
    project: ProjectRepository
    chapter_id: str
    revision: int
    source_hash: str
    content: str


@dataclass(frozen=True, slots=True)
class LinkSpec:
    occurrence_index: int | None
    mention_index: int | None = None
    resolved_subject_id: str | None = None
    role: str = "participant"


def _fixture(
    tmp_path: Path,
    *,
    content: str = "艾琳发现钥匙。",
    fixed_chapter_id: bool = False,
) -> Fixture:
    project = ProjectRepository.create(tmp_path / "project", "Occurrence binding")
    chapter = ChapterRepository(project).create_chapter(
        project.list_volumes()[0].id,
        "Chapter",
        content=content,
    )
    chapter_id = chapter.id
    if fixed_chapter_id:
        with project.database.connect() as connection, connection:
            connection.execute(
                "UPDATE chapters SET id = ? WHERE id = ?",
                (_FIXED_CHAPTER_ID, chapter.id),
            )
        chapter_id = _FIXED_CHAPTER_ID
    return Fixture(project, chapter_id, chapter.revision, _hash(content), content)


def _windows(
    fixture: Fixture,
    *,
    policy: SemanticWindowPolicy | None = None,
) -> tuple[SemanticWindow, ...]:
    return project_semantic_windows(
        fixture.chapter_id,
        fixture.revision,
        fixture.source_hash,
        1,
        fixture.content,
        **({} if policy is None else {"policy": policy}),
    )


def _span(window: SemanticWindow, start: int = 0, end: int = 1) -> SourceSpan:
    return SourceSpan(start, end, window.text[start:end])


def _text_span(window: SemanticWindow, value: str) -> SourceSpan:
    start = window.text.index(value)
    return _span(window, start, start + len(value))


def _result(
    window: SemanticWindow,
    *,
    occurrence_types: tuple[str, ...] = ("DISCOVERY",),
    mention_names: tuple[str, ...] = ("艾琳",),
    link_specs: tuple[LinkSpec, ...] = (LinkSpec(0, mention_index=0),),
    occurrence_spans: tuple[tuple[SourceSpan, ...], ...] | None = None,
    link_spans: tuple[tuple[SourceSpan, ...], ...] | None = None,
    aliases: tuple[AliasCandidate, ...] = (),
    states: tuple[StateChangeCandidate, ...] = (),
    views: tuple[ViewDifferenceCandidate, ...] = (),
    summary: WindowSummaryCandidate | None = None,
) -> SharedSemanticResult:
    mentions = tuple(
        SubjectMentionCandidate(
            candidate_source_id(window, "subject-mention", index),
            name,
            (_text_span(window, name),),
        )
        for index, name in enumerate(mention_names)
    )
    occurrences = tuple(
        OccurrenceCandidate(
            candidate_source_id(window, "occurrence", index),
            occurrence_type,
            f"Event {index}",
            f"Event summary {index}",
            (
                occurrence_spans[index]
                if occurrence_spans is not None
                else (_span(window),)
            ),
        )
        for index, occurrence_type in enumerate(occurrence_types)
    )
    links = tuple(
        ParticipantLinkCandidate(
            candidate_source_id(window, "participant-link", index),
            (
                ResolvedSubjectReference(spec.resolved_subject_id)
                if spec.resolved_subject_id is not None
                else None
            ),
            spec.role,
            f"Subject summary {index}",
            link_spans[index] if link_spans is not None else (_span(window),),
            (
                occurrences[spec.occurrence_index].candidate_id
                if spec.occurrence_index is not None
                else None
            ),
            (
                mentions[spec.mention_index].candidate_id
                if spec.mention_index is not None
                else None
            ),
        )
        for index, spec in enumerate(link_specs)
    )
    return SharedSemanticResult(
        window=window,
        subject_mentions=mentions,
        aliases=aliases,
        occurrences=occurrences,
        participant_links=links,
        state_changes=states,
        view_differences=views,
        summary=summary,
    )


def _chapter_result(
    fixture: Fixture,
    results: tuple[SharedSemanticResult, ...],
) -> SharedSemanticChapterResult:
    return SharedSemanticChapterResult(
        fixture.chapter_id,
        fixture.revision,
        fixture.source_hash,
        1,
        results,
    )


def _table_count(project: ProjectRepository, table: str) -> int:
    with project.database.connect() as connection:
        return int(connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])


def test_persists_complete_multi_window_chapter_once_with_exact_readback(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fixture = _fixture(tmp_path, content="艾琳发现。\n***\n艾琳离开。")
    CharacterMemoryRepository(fixture.project).create_character("艾琳")
    windows = _windows(fixture)
    chapter_result = _chapter_result(
        fixture,
        tuple(_result(window) for window in windows),
    )
    calls = 0
    clock_calls = 0
    original = OccurrenceRepository.create_model_candidates_for_chapter

    def recording_create(self, *args, **kwargs):
        nonlocal calls
        calls += 1
        return original(self, *args, **kwargs)

    monkeypatch.setattr(
        OccurrenceRepository,
        "create_model_candidates_for_chapter",
        recording_create,
    )

    def clock() -> datetime:
        nonlocal clock_calls
        clock_calls += 1
        return _NOW

    binding = SharedSemanticOccurrenceService(
        fixture.project,
        clock=clock,
    ).persist_chapter(chapter_result)

    repository = OccurrenceRepository(fixture.project)
    stored = tuple(
        repository.get_occurrence(item) for item in binding.accepted_occurrence_ids
    )
    assert binding.status is OccurrenceBindingStatus.APPLIED
    assert len(stored) == len(windows) == 2
    assert len(binding.accepted_link_ids) == 2
    assert calls == 1
    assert clock_calls == 1
    assert tuple(item.candidate_source_id for item in stored) == tuple(
        item.occurrences[0].candidate_id for item in chapter_result.results
    )
    assert tuple(item.source_ranges[0].source_start for item in stored) == tuple(
        window.source_start for window in windows
    )
    assert all(item.review_status is ReviewStatus.REVIEW for item in stored)


def test_uuid5_identity_is_frozen_and_replay_does_not_invent_disposition(
    tmp_path: Path,
) -> None:
    fixture = _fixture(tmp_path, fixed_chapter_id=True)
    CharacterMemoryRepository(fixture.project).create_character("艾琳")
    chapter_result = _chapter_result(fixture, (_result(_windows(fixture)[0]),))

    first = SharedSemanticOccurrenceService(
        fixture.project,
        clock=lambda: _NOW,
    ).persist_chapter(chapter_result)
    with fixture.project.database.connect() as connection:
        before = tuple(connection.execute("SELECT * FROM occurrences").fetchone())
        link_before = tuple(
            connection.execute("SELECT * FROM subject_occurrence_links").fetchone()
        )
    replay = SharedSemanticOccurrenceService(
        fixture.project,
        clock=lambda: _NOW + timedelta(days=1),
    ).persist_chapter(chapter_result)
    with fixture.project.database.connect() as connection:
        after = tuple(connection.execute("SELECT * FROM occurrences").fetchone())
        link_after = tuple(
            connection.execute("SELECT * FROM subject_occurrence_links").fetchone()
        )

    assert first.accepted_occurrence_ids == (_EXPECTED_OCCURRENCE_ID,)
    assert first.accepted_link_ids == (_EXPECTED_LINK_ID,)
    assert replay.accepted_occurrence_ids == first.accepted_occurrence_ids
    assert replay.accepted_link_ids == first.accepted_link_ids
    assert first.status is replay.status is OccurrenceBindingStatus.APPLIED
    assert not hasattr(first, "persisted_count")
    assert not hasattr(first, "replayed_count")
    assert after == before
    assert link_after == link_before


def test_exact_types_are_accepted_and_unknown_types_are_omitted_with_links(
    tmp_path: Path,
) -> None:
    fixture = _fixture(tmp_path)
    CharacterMemoryRepository(fixture.project).create_character("艾琳")
    known = (
        "ACTION",
        "CONVERSATION",
        "CONFLICT",
        "DISCOVERY",
        "DECISION",
        "REVELATION",
        "TRANSITION",
        "RELATIONSHIP_CHANGE",
        "OTHER",
    )
    types = (*known, "discovery", " OTHER ")
    result = _result(
        _windows(fixture)[0],
        occurrence_types=types,
        link_specs=(
            *(LinkSpec(index, mention_index=0) for index in range(len(types))),
            LinkSpec(None, mention_index=0),
        ),
    )

    binding = SharedSemanticOccurrenceService(fixture.project).persist_chapter(
        _chapter_result(fixture, (result,))
    )

    with fixture.project.database.connect() as connection:
        stored_types = tuple(
            row[0]
            for row in connection.execute(
                "SELECT type_code FROM occurrences ORDER BY candidate_source_id"
            )
        )
    assert set(stored_types) == set(known)
    assert len(binding.accepted_occurrence_ids) == len(known)
    assert len(binding.accepted_link_ids) == len(known)
    assert [issue.code for issue in binding.issues].count(
        OccurrenceBindingIssueCode.UNKNOWN_OCCURRENCE_TYPE
    ) == 2
    assert [issue.code for issue in binding.issues].count(
        OccurrenceBindingIssueCode.OCCURRENCE_OMITTED
    ) == 2
    assert [issue.code for issue in binding.issues].count(
        OccurrenceBindingIssueCode.MISSING_OCCURRENCE_REFERENCE
    ) == 1


def test_subject_resolution_uses_only_active_canonical_or_confirmed_alias(
    tmp_path: Path,
) -> None:
    fixture = _fixture(tmp_path, content="艾琳小艾未确认陌生同名甲乙")
    characters = CharacterMemoryRepository(fixture.project)
    canonical = characters.create_character("艾琳")
    confirmed = characters.create_character("本名", ("小艾",))
    unconfirmed = characters.create_character("另一人")
    ambiguous_a = characters.create_character("同名")
    characters.create_character("同名")
    resolved_active = characters.create_character("甲")
    resolved_inactive = characters.create_character("乙")
    with fixture.project.database.connect() as connection, connection:
        connection.execute(
            "INSERT INTO subject_aliases VALUES (?, ?, '未确认', ?, 0)",
            (new_id(), unconfirmed.id, unconfirmed.id),
        )
        connection.execute(
            "UPDATE subjects SET active = 0 WHERE id = ?",
            (resolved_inactive.id,),
        )
        before_subject_count = int(
            connection.execute("SELECT COUNT(*) FROM subjects").fetchone()[0]
        )
    window = _windows(fixture)[0]
    alias_span = _text_span(window, "陌生")
    result = _result(
        window,
        occurrence_types=("ACTION",) * 7,
        mention_names=("艾琳", "小艾", "未确认", "陌生", "同名"),
        link_specs=(
            LinkSpec(0, mention_index=0),
            LinkSpec(1, mention_index=1),
            LinkSpec(2, mention_index=2),
            LinkSpec(3, mention_index=3),
            LinkSpec(4, mention_index=4),
            LinkSpec(5, resolved_subject_id=resolved_active.id),
            LinkSpec(6, resolved_subject_id=resolved_inactive.id),
        ),
        aliases=(
            AliasCandidate(
                candidate_source_id(window, "alias", 0),
                "陌生",
                (alias_span,),
            ),
        ),
    )

    binding = SharedSemanticOccurrenceService(fixture.project).persist_chapter(
        _chapter_result(fixture, (result,))
    )

    with fixture.project.database.connect() as connection:
        subjects = {
            row[0]
            for row in connection.execute("SELECT subject_id FROM subject_occurrence_links")
        }
        after_subject_count = int(
            connection.execute("SELECT COUNT(*) FROM subjects").fetchone()[0]
        )
    assert subjects == {canonical.id, confirmed.id, resolved_active.id}
    assert after_subject_count == before_subject_count
    assert {issue.code for issue in binding.issues} == {
        OccurrenceBindingIssueCode.UNRESOLVED_SUBJECT,
        OccurrenceBindingIssueCode.AMBIGUOUS_SUBJECT,
        OccurrenceBindingIssueCode.SUBJECT_UNAVAILABLE,
    }
    assert ambiguous_a.id not in subjects


def test_duplicate_resolved_occurrence_subject_pair_fails_before_p1(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fixture = _fixture(tmp_path, content="艾琳小艾")
    CharacterMemoryRepository(fixture.project).create_character("艾琳", ("小艾",))
    result = _result(
        _windows(fixture)[0],
        mention_names=("艾琳", "小艾"),
        link_specs=(LinkSpec(0, mention_index=0), LinkSpec(0, mention_index=1)),
    )
    calls = 0

    def forbidden_p1(*args, **kwargs) -> None:
        nonlocal calls
        calls += 1

    monkeypatch.setattr(
        OccurrenceRepository,
        "create_model_candidates_for_chapter",
        forbidden_p1,
    )
    binding = SharedSemanticOccurrenceService(fixture.project).persist_chapter(
        _chapter_result(fixture, (result,))
    )

    assert binding.status is OccurrenceBindingStatus.FAILED
    assert binding.failure is not None
    assert (
        binding.failure.code
        is OccurrenceBindingFailureCode.DUPLICATE_RESOLVED_PARTICIPANT
    )
    assert calls == 0
    assert _table_count(fixture.project, "occurrences") == 0


def test_subject_resolution_cache_is_scoped_to_one_chapter_call(tmp_path: Path) -> None:
    fixture = _fixture(tmp_path, content="新人物出现。")
    chapter_result = _chapter_result(
        fixture,
        (_result(_windows(fixture)[0], mention_names=("新人物",)),),
    )
    service = SharedSemanticOccurrenceService(fixture.project)

    first = service.persist_chapter(chapter_result)
    assert first.unresolved_count == 1
    CharacterMemoryRepository(fixture.project).create_character("新人物")
    second = service.persist_chapter(chapter_result)

    assert second.status is OccurrenceBindingStatus.APPLIED
    assert second.accepted_link_count == 1


def test_local_spans_map_to_exact_absolute_crlf_emoji_ranges(
    tmp_path: Path,
) -> None:
    fixture = _fixture(tmp_path, content="前言\r\n\r\n艾😀琳发现。\r\n尾声")
    CharacterMemoryRepository(fixture.project).create_character("艾")
    policy = SemanticWindowPolicy("semantic-window-test", 8, 2)
    windows = _windows(fixture, policy=policy)
    target_index = next(index for index, window in enumerate(windows) if "😀" in window.text)
    target = windows[target_index]
    emoji = target.text.index("😀")
    mention_start = target.text.index("艾")
    results = [SharedSemanticResult(window=window) for window in windows]
    results[target_index] = _result(
        target,
        mention_names=("艾",),
        occurrence_spans=(
            (
                _span(target, mention_start, mention_start + 1),
                _span(target, emoji, emoji + 1),
            ),
        ),
        link_spans=((_span(target, mention_start, mention_start + 1),),),
    )

    binding = SharedSemanticOccurrenceService(fixture.project).persist_chapter(
        _chapter_result(fixture, tuple(results))
    )
    stored = OccurrenceRepository(fixture.project).get_occurrence(
        binding.accepted_occurrence_ids[0]
    )

    assert tuple((item.source_start, item.source_end) for item in stored.source_ranges) == (
        (target.source_start + mention_start, target.source_start + mention_start + 1),
        (target.source_start + emoji, target.source_start + emoji + 1),
    )
    assert stored.source_ranges[0].semantic_window_source_id == target.source_id
    assert stored.source_ranges[0].policy_version == target.policy_version


def test_duplicate_identical_span_fails_whole_chapter_before_p1(
    tmp_path: Path,
) -> None:
    fixture = _fixture(tmp_path)
    CharacterMemoryRepository(fixture.project).create_character("艾琳")
    window = _windows(fixture)[0]
    duplicate = _span(window)
    result = _result(window, occurrence_spans=((duplicate, duplicate),))

    binding = SharedSemanticOccurrenceService(fixture.project).persist_chapter(
        _chapter_result(fixture, (result,))
    )

    assert binding.status is OccurrenceBindingStatus.FAILED
    assert binding.failure is not None
    assert binding.failure.code is OccurrenceBindingFailureCode.INVALID_SOURCE_RANGES
    assert _table_count(fixture.project, "occurrences") == 0


@pytest.mark.parametrize(
    ("field", "size"),
    (("occurrence_title", 501), ("link_role", 101), ("link_summary", 2_001)),
)
def test_o1_domain_incompatible_candidates_are_not_persistence_failures(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    field: str,
    size: int,
) -> None:
    fixture = _fixture(tmp_path)
    CharacterMemoryRepository(fixture.project).create_character("艾琳")
    result = _result(_windows(fixture)[0])
    raw_marker = "S" * size
    if field == "occurrence_title":
        result = replace(
            result,
            occurrences=(replace(result.occurrences[0], title=raw_marker),),
        )
    elif field == "link_role":
        result = replace(
            result,
            participant_links=(
                replace(result.participant_links[0], role=raw_marker),
            ),
        )
    else:
        result = replace(
            result,
            participant_links=(
                replace(result.participant_links[0], subject_summary=raw_marker),
            ),
        )
    p1_calls = 0
    clock_calls = 0

    def forbidden_p1(*args, **kwargs) -> None:
        nonlocal p1_calls
        p1_calls += 1

    def clock() -> datetime:
        nonlocal clock_calls
        clock_calls += 1
        return _NOW

    monkeypatch.setattr(
        OccurrenceRepository,
        "create_model_candidates_for_chapter",
        forbidden_p1,
    )
    binding = SharedSemanticOccurrenceService(
        fixture.project,
        clock=clock,
    ).persist_chapter(_chapter_result(fixture, (result,)))

    assert binding.status is OccurrenceBindingStatus.FAILED
    assert binding.failure is not None
    assert binding.failure.code is OccurrenceBindingFailureCode.INVALID_CANDIDATE
    assert binding.failure.message == "occurrence binding candidate is invalid"
    assert binding.failure.code is not OccurrenceBindingFailureCode.PERSISTENCE_FAILED
    assert raw_marker not in binding.failure.message
    assert p1_calls == 0
    assert clock_calls == 1
    assert _table_count(fixture.project, "occurrences") == 0


@pytest.mark.parametrize("kind", ("occurrences", "links"))
def test_raw_chapter_caps_fail_before_omission_or_p1(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    kind: str,
) -> None:
    fixture = _fixture(tmp_path, content="艾艾")
    CharacterMemoryRepository(fixture.project).create_character("艾")
    policy = SemanticWindowPolicy("semantic-window-cap", 1, 0)
    first, second = _windows(fixture, policy=policy)
    if kind == "occurrences":
        results = (
            _result(
                first,
                occurrence_types=("UNKNOWN",) * 100,
                mention_names=(),
                link_specs=(),
            ),
            _result(
                second,
                occurrence_types=("UNKNOWN",),
                mention_names=(),
                link_specs=(),
            ),
        )
    else:
        results = (
            _result(
                first,
                mention_names=("艾",),
                link_specs=tuple(LinkSpec(0, mention_index=0) for _ in range(500)),
            ),
            _result(
                second,
                mention_names=("艾",),
                link_specs=(LinkSpec(0, mention_index=0),),
            ),
        )
    calls = 0
    clock_calls = 0

    def forbidden_p1(*args, **kwargs) -> None:
        nonlocal calls
        calls += 1

    monkeypatch.setattr(
        OccurrenceRepository,
        "create_model_candidates_for_chapter",
        forbidden_p1,
    )

    def clock() -> datetime:
        nonlocal clock_calls
        clock_calls += 1
        return _NOW

    binding = SharedSemanticOccurrenceService(
        fixture.project,
        clock=clock,
    ).persist_chapter(
        _chapter_result(fixture, results)
    )

    assert binding.status is OccurrenceBindingStatus.FAILED
    assert binding.failure is not None
    assert binding.failure.code is OccurrenceBindingFailureCode.LIMIT_EXCEEDED
    assert calls == 0
    assert clock_calls == 0


def test_empty_chapter_performs_one_empty_source_validating_p1_call(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fixture = _fixture(tmp_path, content=" \r\n ")
    result = _chapter_result(fixture, ())
    calls: list[tuple[tuple[object, ...], tuple[object, ...]]] = []
    clock_calls = 0
    original = OccurrenceRepository.create_model_candidates_for_chapter

    def recording_create(self, chapter_id, **kwargs):
        calls.append((kwargs["occurrences"], kwargs["links"]))
        return original(self, chapter_id, **kwargs)

    monkeypatch.setattr(
        OccurrenceRepository,
        "create_model_candidates_for_chapter",
        recording_create,
    )

    def clock() -> datetime:
        nonlocal clock_calls
        clock_calls += 1
        return _NOW

    binding = SharedSemanticOccurrenceService(
        fixture.project,
        clock=clock,
    ).persist_chapter(result)

    assert binding.status is OccurrenceBindingStatus.APPLIED
    assert binding.accepted_occurrence_ids == binding.accepted_link_ids == ()
    assert calls == [((), ())]
    assert clock_calls == 1


def test_subject_resolution_storage_failure_is_sanitized(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fixture = _fixture(tmp_path)
    result = _chapter_result(fixture, (_result(_windows(fixture)[0]),))

    def raw_storage_failure(*args, **kwargs) -> NoReturn:
        raise sqlite3.OperationalError("RAW SQL SUBJECT SECRET")

    monkeypatch.setattr(
        SubjectRepository,
        "resolve_character_name",
        raw_storage_failure,
    )
    binding = SharedSemanticOccurrenceService(fixture.project).persist_chapter(result)

    assert binding.status is OccurrenceBindingStatus.FAILED
    assert binding.failure is not None
    assert binding.failure.code is OccurrenceBindingFailureCode.PERSISTENCE_FAILED
    assert binding.failure.message == "occurrence binding could not be persisted"
    assert "RAW SQL SUBJECT SECRET" not in binding.failure.message
    assert _table_count(fixture.project, "occurrences") == 0


def test_source_race_and_expected_p1_failure_are_sanitized_without_partial_rows(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fixture = _fixture(tmp_path)
    CharacterMemoryRepository(fixture.project).create_character("艾琳")
    result = _chapter_result(fixture, (_result(_windows(fixture)[0]),))
    ChapterRepository(fixture.project).save_content(
        fixture.chapter_id,
        "changed",
        source="test",
        reason="source race",
        expected_revision=fixture.revision,
    )

    raced = SharedSemanticOccurrenceService(fixture.project).persist_chapter(result)
    assert raced.status is OccurrenceBindingStatus.FAILED
    assert raced.failure is not None
    assert raced.failure.code is OccurrenceBindingFailureCode.PERSISTENCE_FAILED
    assert _table_count(fixture.project, "occurrences") == 0

    def raw_failure(*args, **kwargs) -> NoReturn:
        raise OccurrenceRepositoryError("C:\\secret BODY api-key")

    monkeypatch.setattr(
        OccurrenceRepository,
        "create_model_candidates_for_chapter",
        raw_failure,
    )
    failed = SharedSemanticOccurrenceService(fixture.project).persist_chapter(result)
    assert failed.failure is not None
    assert failed.failure.message == "occurrence binding could not be persisted"
    assert "secret" not in failed.failure.message


def test_invalid_input_envelope_clock_and_base_exception_fail_before_or_through_p1(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fixture = _fixture(tmp_path)
    CharacterMemoryRepository(fixture.project).create_character("艾琳")
    result = _chapter_result(fixture, (_result(_windows(fixture)[0]),))
    calls = 0

    def forbidden_p1(*args, **kwargs) -> None:
        nonlocal calls
        calls += 1

    monkeypatch.setattr(
        OccurrenceRepository,
        "create_model_candidates_for_chapter",
        forbidden_p1,
    )
    service = SharedSemanticOccurrenceService(
        fixture.project,
        clock=lambda: datetime(2026, 8, 21),
    )
    with pytest.raises(TypeError, match="chapter result"):
        service.persist_chapter(object())  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="clock"):
        service.persist_chapter(result)
    assert calls == 0

    object.__setattr__(result, "source_hash", "f" * 64)
    with pytest.raises(ValueError, match="chapter result"):
        SharedSemanticOccurrenceService(fixture.project).persist_chapter(result)
    assert calls == 0

    def stop(*args, **kwargs) -> NoReturn:
        raise KeyboardInterrupt

    monkeypatch.setattr(
        OccurrenceRepository,
        "create_model_candidates_for_chapter",
        stop,
    )
    valid = _chapter_result(fixture, (_result(_windows(fixture)[0]),))
    with pytest.raises(KeyboardInterrupt):
        SharedSemanticOccurrenceService(fixture.project).persist_chapter(valid)


def test_non_occurrence_candidates_are_ignored_without_other_persistence(
    tmp_path: Path,
) -> None:
    fixture = _fixture(tmp_path, content="艾琳知道")
    window = _windows(fixture)[0]
    mention = SubjectMentionCandidate(
        candidate_source_id(window, "subject-mention", 0),
        "艾琳",
        (_span(window, 0, 2),),
    )
    state = StateChangeCandidate(
        candidate_source_id(window, "state-change", 0),
        None,
        "KNOWLEDGE_CHANGE",
        "开始知道",
        (_span(window, 2, 4),),
        None,
        mention.candidate_id,
    )
    view = ViewDifferenceCandidate(
        candidate_source_id(window, "view-difference", 0),
        ViewType.READER_VIEW,
        None,
        None,
        None,
        "读者知道",
        (_span(window, 2, 4),),
        target_mention_candidate_id=mention.candidate_id,
    )
    result = SharedSemanticResult(
        window=window,
        subject_mentions=(mention,),
        aliases=(
            AliasCandidate(
                candidate_source_id(window, "alias", 0),
                "艾琳",
                (_span(window, 0, 2),),
            ),
        ),
        state_changes=(state,),
        view_differences=(view,),
        summary=WindowSummaryCandidate(
            candidate_source_id(window, "window-summary", 0),
            "窗口摘要",
            (_span(window, 0, 4),),
        ),
    )
    before = {
        table: _table_count(fixture.project, table)
        for table in (
            "character_state_events",
            "view_assertions",
            "summary_nodes",
            "subjects",
        )
    }

    binding = SharedSemanticOccurrenceService(fixture.project).persist_chapter(
        _chapter_result(fixture, (result,))
    )

    after = {table: _table_count(fixture.project, table) for table in before}
    assert binding.status is OccurrenceBindingStatus.APPLIED
    assert binding.accepted_occurrence_ids == binding.accepted_link_ids == ()
    assert after == before


def test_binding_dtos_are_immutable_validated_and_body_free() -> None:
    issue = OccurrenceBindingIssue(
        "semantic-window:occurrence:0",
        OccurrenceBindingIssueCode.UNKNOWN_OCCURRENCE_TYPE,
    )
    failure = OccurrenceBindingFailure(
        OccurrenceBindingFailureCode.LIMIT_EXCEEDED,
        "occurrence binding candidate limit exceeded",
    )
    invalid_candidate = OccurrenceBindingFailure(
        OccurrenceBindingFailureCode.INVALID_CANDIDATE,
        "occurrence binding candidate is invalid",
    )
    applied = OccurrenceChapterBindingResult(
        _FIXED_CHAPTER_ID,
        0,
        OccurrenceBindingStatus.APPLIED,
        (_EXPECTED_OCCURRENCE_ID,),
        (),
        (issue,),
        None,
    )

    assert applied.accepted_occurrence_count == 1
    assert applied.failed_count == 0
    assert invalid_candidate.code is OccurrenceBindingFailureCode.INVALID_CANDIDATE
    assert {item.name for item in fields(issue)} == {"candidate_source_id", "code"}
    with pytest.raises(ValueError):
        OccurrenceChapterBindingResult(
            _FIXED_CHAPTER_ID,
            0,
            OccurrenceBindingStatus.FAILED,
            (_EXPECTED_OCCURRENCE_ID,),
            (),
            (),
            failure,
        )
    with pytest.raises(ValueError):
        OccurrenceChapterBindingResult(
            _FIXED_CHAPTER_ID,
            0,
            OccurrenceBindingStatus.APPLIED,
            (_EXPECTED_OCCURRENCE_ID,),
            (_EXPECTED_OCCURRENCE_ID,),
            (),
            None,
        )
    with pytest.raises(ValueError):
        OccurrenceBindingFailure(
            OccurrenceBindingFailureCode.LIMIT_EXCEEDED,
            "RAW BODY",
        )
