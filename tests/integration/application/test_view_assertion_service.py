from pathlib import Path

import pytest

from ai_novel_studio.application.view_assertion_service import (
    ViewAssertionReviewError,
    ViewAssertionService,
)
from ai_novel_studio.domain.memory import (
    Authority,
    KnowledgeState,
    KnowledgeSubject,
    ReviewStatus,
    SourceType,
)
from ai_novel_studio.domain.view import (
    EpistemicStatus,
    ViewAssertionDraft,
    ViewType,
)
from ai_novel_studio.infrastructure.storage.chapter_repository import ChapterRepository
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


def test_user_can_explicitly_replace_one_reviewed_legacy_reader_event(
    tmp_path: Path,
) -> None:
    project, eric, _christine = _project_with_characters(tmp_path)
    volume = project.list_volumes()[0]
    chapter = ChapterRepository(project).create_chapter(
        volume.id,
        "Opening",
        "1",
        "The reader sees the courier.",
    )
    memory = CharacterMemoryRepository(project)
    item = memory.create_knowledge_item(
        "匿名来信",
        "读者看见守夜人投递匿名来信。",
        Authority.USER_CONFIRMED,
        ReviewStatus.APPROVED,
    )
    event = memory.append_knowledge_event(
        item.id,
        KnowledgeSubject.READER,
        project.project.id,
        chapter.id,
        KnowledgeState.KNOWN,
        "第一章正文",
        SourceType.HUMAN,
        ReviewStatus.APPROVED,
    )
    service = ViewAssertionService(project)
    candidates = service.list_legacy_reader_view_candidates()

    assert len(candidates) == 1
    assert candidates[0].event_id == event.id
    assert candidates[0].title == "匿名来信"
    assert candidates[0].detail == "读者看见守夜人投递匿名来信。"
    assert candidates[0].state == KnowledgeState.KNOWN
    assert candidates[0].source_chapter_id == chapter.id
    assert candidates[0].narrative_visible_from_sequence == 2

    with pytest.raises(PermissionError, match="用户明确确认"):
        service.replace_legacy_reader_event(
            legacy_event_id=event.id,
            subject_id=eric.id,
            content="读者已经看见守夜人投递匿名来信。",
            confirmed_by_user=False,
        )
    assertion = service.replace_legacy_reader_event(
        legacy_event_id=event.id,
        subject_id=eric.id,
        content="读者已经看见守夜人投递匿名来信。",
        confirmed_by_user=True,
    )

    assert assertion.source_id == event.id
    assert assertion.source_revision == 0
    assert assertion.narrative_visible_from_sequence == 2
    assert assertion.authority == Authority.USER_CONFIRMED
    assert assertion.review_status == ReviewStatus.APPROVED
    assert service.list_legacy_reader_view_candidates() == ()
    with pytest.raises(ValueError, match="已经存在有效的 Reader View"):
        service.replace_legacy_reader_event(
            legacy_event_id=event.id,
            subject_id=eric.id,
            content="重复接管。",
            confirmed_by_user=True,
        )


def test_legacy_reader_replacement_rejects_wrong_subject_or_unsafe_state(
    tmp_path: Path,
) -> None:
    project, eric, christine = _project_with_characters(tmp_path)
    volume = project.list_volumes()[0]
    chapter = ChapterRepository(project).create_chapter(
        volume.id,
        "Opening",
        "1",
        "Opening body",
    )
    memory = CharacterMemoryRepository(project)
    item = memory.create_knowledge_item(
        "秘密",
        "一条旧知识。",
        Authority.USER_CONFIRMED,
        ReviewStatus.APPROVED,
    )
    character_event = memory.append_knowledge_event(
        item.id,
        KnowledgeSubject.CHARACTER,
        christine.id,
        chapter.id,
        KnowledgeState.KNOWN,
        "人物证据",
        SourceType.HUMAN,
        ReviewStatus.APPROVED,
    )
    forgotten_event = memory.append_knowledge_event(
        item.id,
        KnowledgeSubject.READER,
        project.project.id,
        chapter.id,
        KnowledgeState.FORGOTTEN,
        "读者边界",
        SourceType.HUMAN,
        ReviewStatus.APPROVED,
    )
    pending_item = memory.create_knowledge_item(
        "待审查秘密",
        "这条旧知识还没有经过用户审查。",
        Authority.MODEL_EXTRACTED,
        ReviewStatus.REVIEW,
    )
    pending_event = memory.append_knowledge_event(
        pending_item.id,
        KnowledgeSubject.READER,
        project.project.id,
        chapter.id,
        KnowledgeState.SUSPECTED,
        "模型候选",
        SourceType.MODEL,
        ReviewStatus.REVIEW,
    )
    service = ViewAssertionService(project)
    draft = ViewAssertionDraft(
        subject_id=eric.id,
        view_type=ViewType.READER_VIEW,
        content="读者视角记录。",
        narrative_visible_from_sequence=2,
    )

    assert service.list_legacy_reader_view_candidates() == ()

    with pytest.raises(ValueError, match="不是当前项目的读者知识"):
        service.create_user_reader_view_from_legacy_event(
            draft,
            legacy_event_id=character_event.id,
            confirmed_by_user=True,
        )
    with pytest.raises(ValueError, match="状态不能接管"):
        service.create_user_reader_view_from_legacy_event(
            draft,
            legacy_event_id=forgotten_event.id,
            confirmed_by_user=True,
        )
    with pytest.raises(ValueError, match="尚未审查"):
        service.create_user_reader_view_from_legacy_event(
            draft,
            legacy_event_id=pending_event.id,
            confirmed_by_user=True,
        )


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


def test_chapter_revision_invalidates_view_assertions_without_deleting_them(
    tmp_path: Path,
) -> None:
    project, eric, _christine = _project_with_characters(tmp_path)
    chapters = ChapterRepository(project)
    chapter = chapters.create_chapter(
        project.list_volumes()[0].id,
        "国王的秘密",
        "1",
        "国王仍然活着。",
    )
    service = ViewAssertionService(project)
    approved_model = service.approve_candidate(
        service.create_model_candidate(
            ViewAssertionDraft(
                subject_id=eric.id,
                view_type=ViewType.WORLD_TRUTH,
                content="国王仍然活着。",
            ),
            source_id=chapter.id,
            source_revision=chapter.revision,
        ).id,
        confirmed_by_user=True,
    )
    pending_model = service.create_model_candidate(
        ViewAssertionDraft(
            subject_id=eric.id,
            view_type=ViewType.WORLD_TRUTH,
            content="国王被囚禁在北塔。",
        ),
        source_id=chapter.id,
        source_revision=chapter.revision,
    )
    confirmed_human = service.create_user_assertion(
        ViewAssertionDraft(
            subject_id=eric.id,
            view_type=ViewType.WORLD_TRUTH,
            content="用户确认国王尚在人世。",
        ),
        source_id=chapter.id,
        source_revision=chapter.revision,
        confirmed_by_user=True,
    )
    unrelated = service.create_user_assertion(
        ViewAssertionDraft(
            subject_id=eric.id,
            view_type=ViewType.WORLD_TRUTH,
            content="这条记录来自另一份来源。",
        ),
        source_id="manual-note-unrelated",
        source_revision=0,
        confirmed_by_user=True,
    )

    chapters.save_content(
        chapter.id,
        "国王已经在北塔遇害。",
        source="user_edit",
        reason="rewrite",
    )

    changed_model = service.repository.get(approved_model.id)
    stale_model = service.repository.get(pending_model.id)
    changed_human = service.repository.get(confirmed_human.id)
    assert changed_model.source_changed is True
    assert changed_model.stale is False
    assert changed_model.review_status == ReviewStatus.APPROVED
    assert changed_model.authority == Authority.MODEL_EXTRACTED
    assert stale_model.stale is True
    assert stale_model.source_changed is False
    assert stale_model.review_status == ReviewStatus.REVIEW
    assert changed_human.source_changed is True
    assert changed_human.stale is False
    assert changed_human.content == "用户确认国王尚在人世。"
    assert service.repository.get(unrelated.id) == unrelated
    assert service.list_for_context(
        narrative_sequence=2,
        view_type=ViewType.WORLD_TRUTH,
    ) == (unrelated,)


def test_chapter_save_can_explicitly_skip_view_assertion_invalidation(
    tmp_path: Path,
) -> None:
    project, eric, _christine = _project_with_characters(tmp_path)
    chapters = ChapterRepository(project)
    chapter = chapters.create_chapter(
        project.list_volumes()[0].id,
        "草稿",
        "1",
        "旧内容",
    )
    service = ViewAssertionService(project)
    assertion = service.create_user_assertion(
        ViewAssertionDraft(
            subject_id=eric.id,
            view_type=ViewType.WORLD_TRUTH,
            content="暂不触发记忆失效。",
        ),
        source_id=chapter.id,
        source_revision=chapter.revision,
        confirmed_by_user=True,
    )

    chapters.save_content(
        chapter.id,
        "新内容",
        source="system",
        reason="non-invalidating maintenance",
        invalidate_memory=False,
    )

    assert service.repository.get(assertion.id) == assertion
