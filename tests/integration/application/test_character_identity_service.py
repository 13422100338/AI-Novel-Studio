from dataclasses import replace
from pathlib import Path

import pytest

from ai_novel_studio.application.character_identity_service import (
    CharacterIdentityError,
    CharacterIdentityService,
)
from ai_novel_studio.application.view_assertion_service import ViewAssertionService
from ai_novel_studio.domain.character_identity import CharacterMergeStatus
from ai_novel_studio.domain.generation import CreationMode
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
from ai_novel_studio.infrastructure.storage.chapter_brief_repository import (
    BriefDraftData,
    ChapterBriefRepository,
)
from ai_novel_studio.infrastructure.storage.chapter_repository import ChapterRepository
from ai_novel_studio.infrastructure.storage.character_memory_repository import (
    CharacterMemoryRepository,
)
from ai_novel_studio.infrastructure.storage.project_repository import ProjectRepository
from ai_novel_studio.infrastructure.storage.subject_repository import SubjectRepository


def _project_with_chapter(tmp_path: Path):  # type: ignore[no-untyped-def]
    project = ProjectRepository.create(tmp_path / "project", "人物归并测试")
    volume = project.list_volumes()[0]
    chapter = ChapterRepository(project).create_chapter(volume.id, "第一章", "1")
    return project, chapter


def _brief_data(chapter_id: str, pov_character_id: str) -> BriefDraftData:
    return BriefDraftData(
        chapter_id=chapter_id,
        mode=CreationMode.BASIC,
        dramatic_purpose="建立人物关系",
        target_length=1200,
        story_date="",
        pov_character_id=pov_character_id,
        hard_events=(),
        soft_goals=(),
        prohibited_changes=(),
        creative_freedom=(),
        participants=(),
        knowledge=(),
        clue_actions=(),
        style_rules=(),
        warnings=(),
    )


def test_confirmed_merge_moves_references_hides_source_and_can_be_undone(
    tmp_path: Path,
) -> None:
    project, chapter = _project_with_chapter(tmp_path)
    memory = CharacterMemoryRepository(project)
    source = memory.create_character("艾瑞克", ("艾瑞",), "简称卡片")
    target = memory.create_character("艾瑞克·温德米尔", ("温德米尔",), "正式卡片")
    state = memory.append_state(
        source.id,
        chapter.id,
        motivation="证明自己",
        psychology="克制",
        current_goal="完成述职",
        relationships="信任克莉丝汀",
        recent_activity="收到电报",
        confidence=0.9,
        source_type=SourceType.MODEL,
        review_status=ReviewStatus.REVIEW,
    )
    knowledge = memory.create_knowledge_item(
        "继承人选定",
        "述职会议实际用于选择继承人。",
        Authority.MODEL_EXTRACTED,
        ReviewStatus.REVIEW,
    )
    knowledge_event = memory.append_knowledge_event(
        knowledge.id,
        KnowledgeSubject.CHARACTER,
        source.id,
        chapter.id,
        KnowledgeState.KNOWN,
        "电报内容",
        SourceType.MODEL,
        ReviewStatus.REVIEW,
    )
    brief = ChapterBriefRepository(project).create_draft(
        _brief_data(chapter.id, source.id), ()
    )
    service = CharacterIdentityService(project)
    subjects = SubjectRepository(project)

    with pytest.raises(PermissionError):
        service.merge(
            source.id,
            target.id,
            reason="简称与全称指向同一人物",
            confirmed_by_user=False,
        )

    merge = service.merge(
        source.id,
        target.id,
        reason="简称与全称指向同一人物",
        confirmed_by_user=True,
    )

    assert merge.status == CharacterMergeStatus.APPLIED
    assert merge.moved_state_event_ids == (state.id,)
    assert merge.moved_knowledge_event_ids == (knowledge_event.id,)
    assert merge.moved_brief_ids == (brief.id,)
    assert [item.id for item in memory.list_characters()] == [target.id]
    assert memory.get_character(source.id).canonical_name == "艾瑞克"
    assert memory.get_character(target.id).aliases == ("温德米尔", "艾瑞", "艾瑞克")
    assert subjects.get(source.id).active is False
    assert subjects.get(target.id).active is True
    assert [item.id for item in subjects.resolve_character_name("艾瑞")] == [target.id]
    assert memory.state_history(target.id)[0].id == state.id
    assert (
        memory.latest_knowledge_entries(
            KnowledgeSubject.CHARACTER, target.id, include_review=True
        )[0].event.id
        == knowledge_event.id
    )
    assert ChapterBriefRepository(project).get(brief.id).pov_character_id == target.id

    reversed_merge = service.undo(merge.id, confirmed_by_user=True)

    assert reversed_merge.status == CharacterMergeStatus.REVERSED
    assert [item.id for item in memory.list_characters()] == [source.id, target.id]
    assert memory.get_character(target.id).aliases == ("温德米尔",)
    assert subjects.get(source.id).active is True
    assert [item.id for item in subjects.resolve_character_name("艾瑞")] == [source.id]
    assert memory.state_history(source.id)[0].id == state.id
    assert (
        memory.latest_knowledge_entries(
            KnowledgeSubject.CHARACTER, source.id, include_review=True
        )[0].event.id
        == knowledge_event.id
    )
    assert ChapterBriefRepository(project).get(brief.id).pov_character_id == source.id


def test_merge_moves_only_existing_view_assertion_references_and_undo_restores_them(
    tmp_path: Path,
) -> None:
    project, _chapter = _project_with_chapter(tmp_path)
    memory = CharacterMemoryRepository(project)
    source = memory.create_character("艾瑞克")
    target = memory.create_character("艾瑞克·温德米尔")
    views = ViewAssertionService(project)
    about_source = views.create_user_assertion(
        ViewAssertionDraft(
            subject_id=source.id,
            view_type=ViewType.WORLD_TRUTH,
            content="艾瑞克曾收到王都电报。",
        ),
        source_id="canon-eric-1",
        source_revision=0,
        confirmed_by_user=True,
    )
    source_as_viewer = views.create_user_assertion(
        ViewAssertionDraft(
            subject_id=target.id,
            view_type=ViewType.CHARACTER_VIEW,
            viewer_subject_id=source.id,
            epistemic_status=EpistemicStatus.SUSPECTS,
            content="艾瑞克怀疑正式人物卡记录有误。",
        ),
        source_id="view-eric-1",
        source_revision=0,
        confirmed_by_user=True,
    )
    identities = CharacterIdentityService(project)

    merge = identities.merge(
        source.id,
        target.id,
        reason="用户确认简称与全称属于同一人物",
        confirmed_by_user=True,
    )

    moved_subject = views.repository.get(about_source.id)
    moved_viewer = views.repository.get(source_as_viewer.id)
    assert moved_subject.subject_id == target.id
    assert moved_viewer.viewer_subject_id == target.id
    assert views.list_for_context(
        narrative_sequence=1,
        view_type=ViewType.WORLD_TRUTH,
    ) == (moved_subject,)
    assert views.list_for_context(
        narrative_sequence=1,
        view_type=ViewType.CHARACTER_VIEW,
        viewer_subject_id=target.id,
    ) == (moved_viewer,)

    created_after_merge = views.create_user_assertion(
        ViewAssertionDraft(
            subject_id=target.id,
            view_type=ViewType.WORLD_TRUTH,
            content="这条事实是在归并完成后新建的。",
        ),
        source_id="canon-eric-2",
        source_revision=0,
        confirmed_by_user=True,
    )
    identities.undo(merge.id, confirmed_by_user=True)

    assert views.repository.get(about_source.id).subject_id == source.id
    assert views.repository.get(source_as_viewer.id).viewer_subject_id == source.id
    assert views.repository.get(created_after_merge.id).subject_id == target.id


def test_undo_refuses_to_overwrite_a_view_reference_changed_after_merge(
    tmp_path: Path,
) -> None:
    project, _chapter = _project_with_chapter(tmp_path)
    memory = CharacterMemoryRepository(project)
    source = memory.create_character("艾瑞克")
    target = memory.create_character("艾瑞克·温德米尔")
    third = memory.create_character("克莉丝汀")
    views = ViewAssertionService(project)
    assertion = views.create_user_assertion(
        ViewAssertionDraft(
            subject_id=source.id,
            view_type=ViewType.WORLD_TRUTH,
            content="艾瑞克曾收到王都电报。",
        ),
        source_id="canon-eric-1",
        source_revision=0,
        confirmed_by_user=True,
    )
    identities = CharacterIdentityService(project)
    merge = identities.merge(
        source.id,
        target.id,
        reason="用户确认简称与全称属于同一人物",
        confirmed_by_user=True,
    )
    with project.database.connect() as connection, connection:
        connection.execute(
            "UPDATE view_assertions SET subject_id = ? WHERE id = ?",
            (third.id, assertion.id),
        )

    with pytest.raises(CharacterIdentityError, match="人物引用在归并后又被修改"):
        identities.undo(merge.id, confirmed_by_user=True)

    assert views.repository.get(assertion.id).subject_id == third.id
    assert SubjectRepository(project).get(source.id).active is False


def test_merge_rejects_self_merge_and_duplicate_but_ignores_legacy_mirror_drift(
    tmp_path: Path,
) -> None:
    project, _chapter = _project_with_chapter(tmp_path)
    memory = CharacterMemoryRepository(project)
    source = memory.create_character("艾瑞克")
    target = memory.create_character("艾瑞克·温德米尔")
    service = CharacterIdentityService(project)

    with pytest.raises(CharacterIdentityError, match="同一张"):
        service.merge(source.id, source.id, reason="bad", confirmed_by_user=True)

    merge = service.merge(
        source.id,
        target.id,
        reason="用户确认同一人物",
        confirmed_by_user=True,
    )
    with pytest.raises(CharacterIdentityError, match="已经归并"):
        service.merge(
            source.id,
            target.id,
            reason="重复操作",
            confirmed_by_user=True,
        )

    with project.database.connect() as connection, connection:
        connection.execute(
            "UPDATE characters SET aliases_json = ? WHERE id = ?",
            ('["用户后来新增的别名"]', target.id),
        )
    reversed_merge = service.undo(merge.id, confirmed_by_user=True)

    assert reversed_merge.status == CharacterMergeStatus.REVERSED
    assert memory.get_character(target.id).aliases == ()


def test_undo_rejects_authoritative_subject_alias_changes(tmp_path: Path) -> None:
    project, _chapter = _project_with_chapter(tmp_path)
    memory = CharacterMemoryRepository(project)
    source = memory.create_character("艾瑞克")
    target = memory.create_character("艾瑞克·温德米尔")
    service = CharacterIdentityService(project)
    merge = service.merge(
        source.id,
        target.id,
        reason="用户确认同一人物",
        confirmed_by_user=True,
    )
    with project.database.connect() as connection, connection:
        connection.execute(
            "INSERT INTO subject_aliases "
            "(id, subject_id, alias, source_id, confirmed) VALUES (?, ?, ?, ?, 1)",
            ("manual-alias", target.id, "用户新增的权威别名", "manual-review"),
        )

    with pytest.raises(CharacterIdentityError, match="归并后又被修改"):
        service.undo(merge.id, confirmed_by_user=True)


def test_merge_does_not_store_target_canonical_name_as_its_own_alias(
    tmp_path: Path,
) -> None:
    project, _chapter = _project_with_chapter(tmp_path)
    memory = CharacterMemoryRepository(project)
    source = memory.create_character("艾瑞克", ("小艾",))
    target = memory.create_character("艾瑞克", ("三少爷",))

    CharacterIdentityService(project).merge(
        source.id,
        target.id,
        reason="用户确认两张同名人物卡属于同一人物",
        confirmed_by_user=True,
    )

    aliases = SubjectRepository(project).list_aliases(target.id)
    assert [item.alias for item in aliases] == ["三少爷", "小艾"]


def test_undo_refuses_to_overwrite_brief_edited_after_merge(tmp_path: Path) -> None:
    project, chapter = _project_with_chapter(tmp_path)
    memory = CharacterMemoryRepository(project)
    source = memory.create_character("艾瑞克")
    target = memory.create_character("艾瑞克·温德米尔")
    briefs = ChapterBriefRepository(project)
    brief = briefs.create_draft(_brief_data(chapter.id, source.id), ())
    service = CharacterIdentityService(project)
    merge = service.merge(
        source.id,
        target.id,
        reason="用户确认同一人物",
        confirmed_by_user=True,
    )
    edited = replace(
        _brief_data(chapter.id, target.id),
        dramatic_purpose="归并后由用户修改",
    )
    briefs.update_draft(brief.id, edited, expected_revision=1)

    with pytest.raises(CharacterIdentityError, match="Brief 在归并后又被修改"):
        service.undo(merge.id, confirmed_by_user=True)

    assert briefs.get(brief.id).dramatic_purpose == "归并后由用户修改"
    assert memory.get_character(target.id).aliases == ("艾瑞克",)
