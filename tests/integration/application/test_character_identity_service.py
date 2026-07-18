from dataclasses import replace
from pathlib import Path

import pytest

from ai_novel_studio.application.character_identity_service import (
    CharacterIdentityError,
    CharacterIdentityService,
)
from ai_novel_studio.domain.character_identity import CharacterMergeStatus
from ai_novel_studio.domain.generation import CreationMode
from ai_novel_studio.domain.memory import (
    Authority,
    KnowledgeState,
    KnowledgeSubject,
    ReviewStatus,
    SourceType,
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
    assert memory.get_character(target.id).aliases == ("温德米尔", "艾瑞克", "艾瑞")
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


def test_merge_rejects_self_merge_duplicate_merge_and_stale_undo(tmp_path: Path) -> None:
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
