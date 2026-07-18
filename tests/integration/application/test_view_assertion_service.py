from pathlib import Path

import pytest

from ai_novel_studio.application.view_assertion_service import (
    ViewAssertionReviewError,
    ViewAssertionService,
)
from ai_novel_studio.domain.memory import Authority, ReviewStatus, SourceType
from ai_novel_studio.domain.view import (
    EpistemicStatus,
    ViewAssertionDraft,
    ViewType,
)
from ai_novel_studio.infrastructure.storage.character_memory_repository import (
    CharacterMemoryRepository,
)
from ai_novel_studio.infrastructure.storage.project_repository import ProjectRepository


def _project_with_characters(tmp_path: Path):  # type: ignore[no-untyped-def]
    project = ProjectRepository.create(tmp_path / "project", "View Assertion Test")
    characters = CharacterMemoryRepository(project)
    eric = characters.create_character("艾瑞克")
    christine = characters.create_character("克莉丝汀")
    return project, eric, christine


def test_character_view_requires_explicit_user_confirmation_and_viewer(
    tmp_path: Path,
) -> None:
    project, eric, christine = _project_with_characters(tmp_path)
    service = ViewAssertionService(project)
    draft = ViewAssertionDraft(
        subject_id=eric.id,
        view_type=ViewType.CHARACTER_VIEW,
        viewer_subject_id=christine.id,
        epistemic_status=EpistemicStatus.BELIEVES,
        content="克莉丝汀相信国王已经死亡。",
        valid_from_sequence=3,
    )

    with pytest.raises(PermissionError, match="用户明确确认"):
        service.create_user_assertion(
            draft,
            source_id="manual-note-1",
            source_revision=0,
            confirmed_by_user=False,
        )

    assertion = service.create_user_assertion(
        draft,
        source_id="manual-note-1",
        source_revision=0,
        confirmed_by_user=True,
    )

    assert assertion.view_type == ViewType.CHARACTER_VIEW
    assert assertion.viewer_subject_id == christine.id
    assert assertion.epistemic_status == EpistemicStatus.BELIEVES
    assert service.list_for_context(
        narrative_sequence=2,
        view_type=ViewType.CHARACTER_VIEW,
        viewer_subject_id=christine.id,
    ) == ()
    assert service.list_for_context(
        narrative_sequence=3,
        view_type=ViewType.CHARACTER_VIEW,
        viewer_subject_id=christine.id,
    ) == (assertion,)


def test_reader_view_stays_sparse_and_blocks_premature_reveal(tmp_path: Path) -> None:
    project, eric, _christine = _project_with_characters(tmp_path)
    service = ViewAssertionService(project)
    reader_assertion = service.create_user_assertion(
        ViewAssertionDraft(
            subject_id=eric.id,
            view_type=ViewType.READER_VIEW,
            content="读者可以知道父亲可能另有苦衷。",
            narrative_visible_from_sequence=10,
            story_time_label="第二部前期",
        ),
        source_id="reader-plan-1",
        source_revision=1,
        confirmed_by_user=True,
    )

    assert service.list_for_context(
        narrative_sequence=9,
        view_type=ViewType.READER_VIEW,
    ) == ()
    assert service.list_for_context(
        narrative_sequence=10,
        view_type=ViewType.READER_VIEW,
    ) == (reader_assertion,)
    assert service.list_for_context(
        narrative_sequence=10,
        view_type=ViewType.CHARACTER_VIEW,
        viewer_subject_id=eric.id,
    ) == ()


def test_unknown_is_absence_and_unaware_must_be_explicit(tmp_path: Path) -> None:
    project, eric, christine = _project_with_characters(tmp_path)
    service = ViewAssertionService(project)

    assert service.list_for_context(
        narrative_sequence=5,
        view_type=ViewType.CHARACTER_VIEW,
        viewer_subject_id=christine.id,
    ) == ()

    unaware = service.create_user_assertion(
        ViewAssertionDraft(
            subject_id=eric.id,
            view_type=ViewType.CHARACTER_VIEW,
            viewer_subject_id=christine.id,
            epistemic_status=EpistemicStatus.UNAWARE,
            content="克莉丝汀此时明确不知道艾瑞克的真实身份。",
            valid_from_sequence=4,
            valid_to_sequence=8,
        ),
        source_id="secret-control-1",
        source_revision=0,
        confirmed_by_user=True,
    )

    assert service.list_for_context(
        narrative_sequence=5,
        view_type=ViewType.CHARACTER_VIEW,
        viewer_subject_id=christine.id,
    ) == (unaware,)
    assert service.list_for_context(
        narrative_sequence=9,
        view_type=ViewType.CHARACTER_VIEW,
        viewer_subject_id=christine.id,
    ) == ()


def test_context_filter_excludes_stale_and_source_changed_assertions(
    tmp_path: Path,
) -> None:
    project, eric, _christine = _project_with_characters(tmp_path)
    service = ViewAssertionService(project)
    stale = service.create_user_assertion(
        ViewAssertionDraft(
            subject_id=eric.id,
            view_type=ViewType.WORLD_TRUTH,
            content="This fact is derived from an obsolete source.",
        ),
        source_id="canon-1",
        source_revision=2,
        confirmed_by_user=True,
    )
    changed = service.create_user_assertion(
        ViewAssertionDraft(
            subject_id=eric.id,
            view_type=ViewType.WORLD_TRUTH,
            content="This confirmed fact needs review after its source changed.",
        ),
        source_id="canon-2",
        source_revision=3,
        confirmed_by_user=True,
    )
    with project.database.connect() as connection, connection:
        connection.execute(
            "UPDATE view_assertions SET stale = 1 WHERE id = ?",
            (stale.id,),
        )
        connection.execute(
            "UPDATE view_assertions SET source_changed = 1 WHERE id = ?",
            (changed.id,),
        )

    assert service.list_for_context(
        narrative_sequence=20,
        view_type=ViewType.WORLD_TRUTH,
    ) == ()


def test_author_plan_and_world_truth_remain_separate(tmp_path: Path) -> None:
    project, eric, _christine = _project_with_characters(tmp_path)
    service = ViewAssertionService(project)
    plan = service.create_user_assertion(
        ViewAssertionDraft(
            subject_id=eric.id,
            view_type=ViewType.AUTHOR_PLAN,
            content="The author plans for Eric to leave in chapter twelve.",
        ),
        source_id="outline-12",
        source_revision=0,
        confirmed_by_user=True,
    )

    assert service.list_for_context(
        narrative_sequence=11,
        view_type=ViewType.AUTHOR_PLAN,
    ) == (plan,)
    assert service.list_for_context(
        narrative_sequence=11,
        view_type=ViewType.WORLD_TRUTH,
    ) == ()


def test_context_filter_excludes_assertions_for_inactive_subjects(
    tmp_path: Path,
) -> None:
    project, eric, _christine = _project_with_characters(tmp_path)
    service = ViewAssertionService(project)
    service.create_user_assertion(
        ViewAssertionDraft(
            subject_id=eric.id,
            view_type=ViewType.WORLD_TRUTH,
            content="This identity has since been merged into another subject.",
        ),
        source_id="canon-old-subject",
        source_revision=0,
        confirmed_by_user=True,
    )
    with project.database.connect() as connection, connection:
        connection.execute(
            "UPDATE subjects SET active = 0 WHERE id = ?",
            (eric.id,),
        )

    assert service.list_for_context(
        narrative_sequence=1,
        view_type=ViewType.WORLD_TRUTH,
    ) == ()


def test_model_candidate_stays_out_of_context_until_explicit_approval(
    tmp_path: Path,
) -> None:
    project, eric, _christine = _project_with_characters(tmp_path)
    service = ViewAssertionService(project)
    candidate = service.create_model_candidate(
        ViewAssertionDraft(
            subject_id=eric.id,
            view_type=ViewType.WORLD_TRUTH,
            content="模型认为国王仍然活着。",
        ),
        source_id="chapter-8",
        source_revision=3,
    )

    assert candidate.authority == Authority.MODEL_EXTRACTED
    assert candidate.review_status == ReviewStatus.REVIEW
    assert candidate.source_type == SourceType.MODEL
    assert service.list_review_candidates() == (candidate,)
    assert service.list_for_context(
        narrative_sequence=8,
        view_type=ViewType.WORLD_TRUTH,
    ) == ()
    with pytest.raises(PermissionError, match="用户明确确认"):
        service.approve_candidate(candidate.id, confirmed_by_user=False)
    with pytest.raises(PermissionError, match="用户明确确认"):
        service.approve_candidate(
            candidate.id,
            confirmed_by_user="yes",  # type: ignore[arg-type]
        )

    approved = service.approve_candidate(candidate.id, confirmed_by_user=True)

    assert approved.authority == Authority.MODEL_EXTRACTED
    assert approved.review_status == ReviewStatus.APPROVED
    assert service.list_review_candidates() == ()
    assert service.list_for_context(
        narrative_sequence=8,
        view_type=ViewType.WORLD_TRUTH,
    ) == (approved,)


def test_rejected_model_candidate_cannot_be_approved_later(tmp_path: Path) -> None:
    project, eric, _christine = _project_with_characters(tmp_path)
    service = ViewAssertionService(project)
    candidate = service.create_model_candidate(
        ViewAssertionDraft(
            subject_id=eric.id,
            view_type=ViewType.AUTHOR_PLAN,
            content="模型猜测作者计划让艾瑞克离开领地。",
        ),
        source_id="outline-5",
        source_revision=1,
    )

    with pytest.raises(PermissionError, match="用户明确确认"):
        service.reject_candidate(candidate.id, confirmed_by_user=False)
    rejected = service.reject_candidate(candidate.id, confirmed_by_user=True)

    assert rejected.review_status == ReviewStatus.REJECTED
    with pytest.raises(ViewAssertionReviewError, match="不能重复审查"):
        service.approve_candidate(candidate.id, confirmed_by_user=True)
    assert service.list_for_context(
        narrative_sequence=20,
        view_type=ViewType.AUTHOR_PLAN,
    ) == ()

    human_assertion = service.create_user_assertion(
        ViewAssertionDraft(
            subject_id=eric.id,
            view_type=ViewType.AUTHOR_PLAN,
            content="用户直接建立的作者计划。",
        ),
        source_id="manual-plan",
        source_revision=0,
        confirmed_by_user=True,
    )
    with pytest.raises(ViewAssertionReviewError, match="只有模型提取候选"):
        service.reject_candidate(human_assertion.id, confirmed_by_user=True)


def test_changed_or_stale_model_candidates_require_regeneration(
    tmp_path: Path,
) -> None:
    project, eric, _christine = _project_with_characters(tmp_path)
    service = ViewAssertionService(project)
    stale = service.create_model_candidate(
        ViewAssertionDraft(
            subject_id=eric.id,
            view_type=ViewType.WORLD_TRUTH,
            content="来自旧章节修订的候选。",
        ),
        source_id="chapter-2",
        source_revision=1,
    )
    changed = service.create_model_candidate(
        ViewAssertionDraft(
            subject_id=eric.id,
            view_type=ViewType.WORLD_TRUTH,
            content="来源已经发生变化的候选。",
        ),
        source_id="chapter-3",
        source_revision=2,
    )
    with project.database.connect() as connection, connection:
        connection.execute(
            "UPDATE view_assertions SET stale = 1 WHERE id = ?",
            (stale.id,),
        )
        connection.execute(
            "UPDATE view_assertions SET source_changed = 1 WHERE id = ?",
            (changed.id,),
        )

    assert service.list_review_candidates() == ()
    for candidate in (stale, changed):
        with pytest.raises(ViewAssertionReviewError, match="来源已经变化"):
            service.approve_candidate(candidate.id, confirmed_by_user=True)
