from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path

import pytest

from ai_novel_studio.application.shared_semantic_import_service import (
    SharedSemanticChapterResult,
)
from ai_novel_studio.application.shared_semantic_view_service import (
    SharedSemanticViewBindingStatus,
    SharedSemanticViewIssueCode,
    SharedSemanticViewService,
)
from ai_novel_studio.core.context.semantic_windowing import (
    SemanticWindow,
    project_semantic_windows,
)
from ai_novel_studio.core.context.shared_semantic_result import (
    ResolvedSubjectReference,
    SharedSemanticResult,
    SourceSpan,
    SubjectMentionCandidate,
    ViewDifferenceCandidate,
    ViewDifferenceKind,
    candidate_source_id,
)
from ai_novel_studio.domain.memory import Authority
from ai_novel_studio.domain.view import EpistemicStatus, ViewType
from ai_novel_studio.infrastructure.storage.chapter_repository import ChapterRepository
from ai_novel_studio.infrastructure.storage.character_memory_repository import (
    CharacterMemoryRepository,
)
from ai_novel_studio.infrastructure.storage.project_repository import ProjectRepository
from ai_novel_studio.infrastructure.storage.view_assertion_repository import (
    ViewAssertionRepository,
    ViewAssertionRepositoryError,
)


def _hash(content: str) -> str:
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


@dataclass(frozen=True, slots=True)
class Fixture:
    project: ProjectRepository
    chapter_id: str
    revision: int
    source_hash: str
    content: str


def _fixture(
    tmp_path: Path,
    *,
    content: str = "艾琳低声告诉守卫，读者只看见背影。",
) -> Fixture:
    project = ProjectRepository.create(tmp_path / "project", "Shared views")
    chapter = ChapterRepository(project).create_chapter(
        project.list_volumes()[0].id,
        "Chapter",
        content=content,
    )
    return Fixture(
        project,
        chapter.id,
        chapter.revision,
        _hash(content),
        content,
    )


def _windows(fixture: Fixture) -> tuple[SemanticWindow, ...]:
    return project_semantic_windows(
        fixture.chapter_id,
        fixture.revision,
        fixture.source_hash,
        1,
        fixture.content,
    )


def _span(window: SemanticWindow, value: str) -> SourceSpan:
    start = window.text.index(value)
    return SourceSpan(
        start,
        start + len(value),
        window.text[start : start + len(value)],
    )


@dataclass(frozen=True, slots=True)
class ViewSpec:
    anchor: str
    content: str
    target: str | None
    observer: str | None = None
    view_type: str = "READER_VIEW"
    epistemic_status: EpistemicStatus | None = None
    kind: ViewDifferenceKind | None = None
    resolved_target: ResolvedSubjectReference | None = None
    resolved_observer: ResolvedSubjectReference | None = None


def _result(
    window: SemanticWindow,
    *,
    mention_names: tuple[str, ...] = (),
    views: tuple[ViewSpec, ...] = (),
) -> SharedSemanticResult:
    mentions = tuple(
        SubjectMentionCandidate(
            candidate_source_id(window, "subject-mention", index),
            name,
            (_span(window, name),),
        )
        for index, name in enumerate(mention_names)
    )
    mention_ids = {
        name: mentions[index].candidate_id
        for index, name in enumerate(mention_names)
    }

    def _candidate(index: int, spec: ViewSpec) -> ViewDifferenceCandidate:
        if spec.resolved_observer is not None or spec.resolved_target is not None:
            return ViewDifferenceCandidate(
                candidate_id=candidate_source_id(window, "view-difference", index),
                view_type=ViewType(spec.view_type),
                observer=spec.resolved_observer,
                target=spec.resolved_target,
                epistemic_status=spec.epistemic_status,
                content=spec.content,
                spans=(_span(window, spec.anchor),),
                difference_kind=spec.kind,
            )
        return ViewDifferenceCandidate(
            candidate_id=candidate_source_id(window, "view-difference", index),
            view_type=ViewType(spec.view_type),
            observer=None,
            target=None,
            epistemic_status=spec.epistemic_status,
            content=spec.content,
            spans=(_span(window, spec.anchor),),
            observer_mention_candidate_id=(
                mention_ids[spec.observer] if spec.observer is not None else None
            ),
            target_mention_candidate_id=(
                mention_ids[spec.target] if spec.target is not None else None
            ),
            difference_kind=spec.kind,
        )

    return SharedSemanticResult(
        window=window,
        subject_mentions=mentions,
        aliases=(),
        occurrences=(),
        participant_links=(),
        state_changes=(),
        view_differences=tuple(
            _candidate(index, spec) for index, spec in enumerate(views)
        ),
        summary=None,
    )


def _chapter(
    fixture: Fixture,
    results: tuple[SharedSemanticResult, ...],
) -> SharedSemanticChapterResult:
    return SharedSemanticChapterResult(
        chapter_id=fixture.chapter_id,
        source_revision=fixture.revision,
        source_hash=fixture.source_hash,
        narrative_sequence=1,
        results=results,
    )


_CHARACTER_VIEW = dict(
    view_type="CHARACTER_VIEW",
    observer="艾琳",
    target="守卫",
    epistemic_status=EpistemicStatus.MISBELIEVES,
    kind=ViewDifferenceKind.FALSE_BELIEF,
    anchor="艾琳",
)
_READER_VIEW = dict(
    view_type="READER_VIEW",
    target="艾琳",
    kind=ViewDifferenceKind.PARTIAL_DISCLOSURE,
    anchor="背影",
)


def test_binds_resolved_views_once_with_derived_visibility(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fixture = _fixture(tmp_path)
    characters = CharacterMemoryRepository(fixture.project)
    first_subject = characters.create_character("艾琳")
    second_subject = characters.create_character("守卫")
    windows = _windows(fixture)
    results = tuple(
        _result(
            window,
            mention_names=("艾琳", "守卫"),
            views=(
                ViewSpec(content="艾琳误信守卫已离开。", **_CHARACTER_VIEW),
                ViewSpec(content="读者只见部分真相。", **_READER_VIEW),
            ),
        )
        for window in windows
    )
    calls: list[int] = []
    original = ViewAssertionRepository.create_model_candidates_for_chapter

    def recording(self, drafts, **kwargs):
        calls.append(1)
        return original(self, drafts, **kwargs)

    monkeypatch.setattr(
        ViewAssertionRepository,
        "create_model_candidates_for_chapter",
        recording,
    )

    bound = SharedSemanticViewService(fixture.project).bind_chapter_views(
        _chapter(fixture, results)
    )

    assert bound.status is SharedSemanticViewBindingStatus.APPLIED
    assert bound.failure is None
    assert len(bound.accepted_assertion_ids) == 2 * len(windows)
    assert len(calls) == 1
    repository = ViewAssertionRepository(fixture.project)
    sequence = ChapterRepository(fixture.project).get_chapter_sequence(
        fixture.chapter_id
    )
    stored = tuple(repository.get(item) for item in bound.accepted_assertion_ids)
    for assertion in stored:
        assert assertion.authority is Authority.MODEL_EXTRACTED
        assert assertion.narrative_visible_from_sequence == sequence + 1
    character_rows = [
        item for item in stored if item.view_type is ViewType.CHARACTER_VIEW
    ]
    reader_rows = [
        item for item in stored if item.view_type is ViewType.READER_VIEW
    ]
    assert len(character_rows) == len(windows)
    assert len(reader_rows) == len(windows)
    for assertion in character_rows:
        assert assertion.subject_id == second_subject.id
        assert assertion.viewer_subject_id == first_subject.id
        assert assertion.epistemic_status is EpistemicStatus.MISBELIEVES
    for assertion in reader_rows:
        assert assertion.subject_id == first_subject.id
        assert assertion.viewer_subject_id is None
        assert assertion.epistemic_status is None


def test_unresolved_and_ambiguous_mentions_become_bounded_issues(
    tmp_path: Path,
) -> None:
    fixture = _fixture(tmp_path, content="陌生来客。守卫旁观。同名甲乙互望。")
    characters = CharacterMemoryRepository(fixture.project)
    kept = characters.create_character("守卫")
    characters.create_character("同名")
    characters.create_character("同名")
    window = _windows(fixture)[0]
    chapter = _chapter(
        fixture,
        (
            _result(
                window,
                mention_names=("陌生", "同名", "守卫"),
                views=(
                    ViewSpec(
                        anchor="陌生",
                        content="来客不可见。",
                        target="陌生",
                        kind=ViewDifferenceKind.PARTIAL_DISCLOSURE,
                    ),
                    ViewSpec(
                        anchor="同名",
                        view_type="CHARACTER_VIEW",
                        content="互望归属不明。",
                        observer="同名",
                        target="守卫",
                        epistemic_status=EpistemicStatus.SUSPECTS,
                        kind=ViewDifferenceKind.SUSPICION,
                    ),
                    ViewSpec(
                        anchor="守卫",
                        content="守卫被目击。",
                        target="守卫",
                        kind=ViewDifferenceKind.PARTIAL_DISCLOSURE,
                    ),
                ),
            ),
        ),
    )

    bound = SharedSemanticViewService(fixture.project).bind_chapter_views(chapter)

    assert bound.status is SharedSemanticViewBindingStatus.APPLIED
    issue_codes = {item.code for item in bound.issues}
    assert issue_codes == {
        SharedSemanticViewIssueCode.UNRESOLVED_SUBJECT,
        SharedSemanticViewIssueCode.AMBIGUOUS_SUBJECT,
    }
    assert len(bound.accepted_assertion_ids) == 1
    stored = ViewAssertionRepository(fixture.project).get(
        bound.accepted_assertion_ids[0]
    )
    assert stored.subject_id == kept.id


def test_resolved_reference_paths_use_active_characters_directly(
    tmp_path: Path,
) -> None:
    fixture = _fixture(tmp_path)
    characters = CharacterMemoryRepository(fixture.project)
    first_subject = characters.create_character("艾琳")
    second_subject = characters.create_character("守卫")
    window = _windows(fixture)[0]
    chapter = _chapter(
        fixture,
        (
            _result(
                window,
                views=(
                    ViewSpec(
                        anchor="艾琳",
                        view_type="CHARACTER_VIEW",
                        content="直接引用的观察。",
                        epistemic_status=EpistemicStatus.SUSPECTS,
                        kind=ViewDifferenceKind.SUSPICION,
                        resolved_observer=ResolvedSubjectReference(first_subject.id),
                        resolved_target=ResolvedSubjectReference(second_subject.id),
                        target=None,
                        observer=None,
                    ),
                ),
            ),
        ),
    )

    bound = SharedSemanticViewService(fixture.project).bind_chapter_views(chapter)

    assert bound.status is SharedSemanticViewBindingStatus.APPLIED
    assert bound.issues == ()
    stored = ViewAssertionRepository(fixture.project).get(
        bound.accepted_assertion_ids[0]
    )
    assert stored.subject_id == second_subject.id
    assert stored.viewer_subject_id == first_subject.id


def test_source_race_fails_whole_chapter_closed(tmp_path: Path) -> None:
    fixture = _fixture(tmp_path)
    CharacterMemoryRepository(fixture.project).create_character("艾琳")
    windows = _windows(fixture)
    chapter = _chapter(
        fixture,
        tuple(
            _result(
                window,
                mention_names=("艾琳",),
                views=(ViewSpec(content="读者误会。", **_READER_VIEW),),
            )
            for window in windows
        ),
    )
    ChapterRepository(fixture.project).save_content(
        fixture.chapter_id,
        "并发修改后的正文。",
        source="test",
        reason="source race",
        expected_revision=fixture.revision,
    )

    bound = SharedSemanticViewService(fixture.project).bind_chapter_views(chapter)

    assert bound.status is SharedSemanticViewBindingStatus.FAILED
    assert bound.accepted_assertion_ids == ()
    assert bound.failure is not None
    assert (
        bound.failure.message == "shared semantic view binding could not be persisted"
    )
    with fixture.project.database.connect() as connection:
        count = int(
            connection.execute("SELECT COUNT(*) FROM view_assertions").fetchone()[0]
        )
    assert count == 0


def test_rebinding_same_revision_fails_without_duplicates(tmp_path: Path) -> None:
    fixture = _fixture(tmp_path)
    CharacterMemoryRepository(fixture.project).create_character("艾琳")
    chapter = _chapter(
        fixture,
        tuple(
            _result(
                window,
                mention_names=("艾琳",),
                views=(ViewSpec(content="读者误会。", **_READER_VIEW),),
            )
            for window in _windows(fixture)
        ),
    )
    service = SharedSemanticViewService(fixture.project)

    first = service.bind_chapter_views(chapter)
    second = service.bind_chapter_views(chapter)

    assert first.status is SharedSemanticViewBindingStatus.APPLIED
    assert second.status is SharedSemanticViewBindingStatus.FAILED
    assert second.accepted_assertion_ids == ()
    repository = ViewAssertionRepository(fixture.project)
    stored = tuple(repository.get(item) for item in first.accepted_assertion_ids)
    assert all(item.review_status.value == "REVIEW" for item in stored)


def test_empty_views_bind_with_single_boundary_call(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fixture = _fixture(tmp_path)
    calls: list[int] = []
    original = ViewAssertionRepository.create_model_candidates_for_chapter

    def recording(self, drafts, **kwargs):
        calls.append(len(drafts))
        return original(self, drafts, **kwargs)

    monkeypatch.setattr(
        ViewAssertionRepository,
        "create_model_candidates_for_chapter",
        recording,
    )

    bound = SharedSemanticViewService(fixture.project).bind_chapter_views(
        _chapter(fixture, tuple(_result(window) for window in _windows(fixture)))
    )

    assert bound.status is SharedSemanticViewBindingStatus.APPLIED
    assert bound.accepted_assertion_ids == ()
    assert bound.issues == ()
    assert len(calls) == 1
    assert all(size == 0 for size in calls)


def test_base_exception_from_boundary_propagates(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fixture = _fixture(tmp_path)
    CharacterMemoryRepository(fixture.project).create_character("艾琳")

    def stop(*args, **kwargs):
        raise KeyboardInterrupt

    monkeypatch.setattr(
        ViewAssertionRepository,
        "create_model_candidates_for_chapter",
        stop,
    )
    with pytest.raises(KeyboardInterrupt):
        SharedSemanticViewService(fixture.project).bind_chapter_views(
            _chapter(
                fixture,
                tuple(
                    _result(
                        window,
                        mention_names=("艾琳",),
                        views=(ViewSpec(content="读者误会。", **_READER_VIEW),),
                    )
                    for window in _windows(fixture)
                ),
            )
        )


def test_storage_failures_are_sanitized(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fixture = _fixture(tmp_path)
    CharacterMemoryRepository(fixture.project).create_character("艾琳")

    def raw_failure(*args, **kwargs):
        raise ViewAssertionRepositoryError("RAW STORAGE SECRET C:\\path")

    monkeypatch.setattr(
        ViewAssertionRepository,
        "create_model_candidates_for_chapter",
        raw_failure,
    )
    bound = SharedSemanticViewService(fixture.project).bind_chapter_views(
        _chapter(
            fixture,
            tuple(
                _result(
                    window,
                    mention_names=("艾琳",),
                    views=(ViewSpec(content="读者误会。", **_READER_VIEW),),
                )
                for window in _windows(fixture)
            ),
        )
    )

    assert bound.status is SharedSemanticViewBindingStatus.FAILED
    assert bound.failure is not None
    assert (
        bound.failure.message == "shared semantic view binding could not be persisted"
    )
    assert "RAW" not in bound.failure.message


def test_envelope_identity_mismatch_rejected_before_write(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fixture = _fixture(tmp_path)

    def forbidden_write(self, drafts, **kwargs):
        raise AssertionError("inconsistent envelope must not reach boundary")

    monkeypatch.setattr(
        ViewAssertionRepository,
        "create_model_candidates_for_chapter",
        forbidden_write,
    )
    windows = _windows(fixture)
    with pytest.raises(ValueError, match="shared semantic chapter"):
        SharedSemanticChapterResult(
            chapter_id=fixture.chapter_id,
            source_revision=fixture.revision,
            source_hash=fixture.source_hash,
            narrative_sequence=2,
            results=windows,
        )
    consistent = _chapter(
        fixture, tuple(_result(window) for window in windows)
    )
    corrupted = _chapter(
        fixture, tuple(_result(window) for window in windows)
    )
    object.__setattr__(corrupted, "narrative_sequence", 2)

    service = SharedSemanticViewService(fixture.project)
    with pytest.raises(ValueError, match="shared semantic view"):
        service.bind_chapter_views(corrupted)
    assert consistent.narrative_sequence == 1
    with pytest.raises(TypeError):
        service.bind_chapter_views(object())  # type: ignore[arg-type]
