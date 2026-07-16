from pathlib import Path

import pytest

from ai_novel_studio.application.brief_context_provider import (
    BriefCompilationRequest,
    BriefContextProvider,
)
from ai_novel_studio.application.brief_lifecycle_service import (
    BriefLifecycleService,
    BriefValidationError,
)
from ai_novel_studio.application.chapter_brief_compiler import ChapterBriefCompiler
from ai_novel_studio.application.chapter_requirement_service import ChapterRequirementService
from ai_novel_studio.domain.generation import BriefStatus, CreationMode
from ai_novel_studio.domain.memory import (
    Authority,
    ClueAction,
    ClueType,
    KnowledgeState,
    KnowledgeSubject,
    MemoryStatus,
    ReviewStatus,
    SourceType,
    StyleScope,
)
from ai_novel_studio.infrastructure.storage.chapter_brief_repository import (
    ChapterBriefRepository,
)
from ai_novel_studio.infrastructure.storage.chapter_repository import ChapterRepository
from ai_novel_studio.infrastructure.storage.chapter_requirement_repository import (
    ChapterRequirementRepository,
    StaleRequirementError,
)
from ai_novel_studio.infrastructure.storage.character_memory_repository import (
    CharacterMemoryRepository,
)
from ai_novel_studio.infrastructure.storage.narrative_memory_repository import (
    NarrativeMemoryRepository,
)
from ai_novel_studio.infrastructure.storage.project_repository import ProjectRepository
from ai_novel_studio.infrastructure.storage.search_repository import SearchRepository
from ai_novel_studio.infrastructure.storage.style_repository import StyleRepository


def _workspace(tmp_path: Path):  # type: ignore[no-untyped-def]
    project = ProjectRepository.create(tmp_path / "project", "编译测试")
    volume = project.list_volumes()[0]
    chapters = ChapterRepository(project)
    previous = chapters.create_chapter(volume.id, "前章", "1", "旧暗号第一次出现")
    current = chapters.create_chapter(volume.id, "当前章", "2", "")
    future = chapters.create_chapter(volume.id, "未来章", "3", "")
    requirement_repository = ChapterRequirementRepository(project)
    requirement_service = ChapterRequirementService(requirement_repository)
    created = requirement_service.get_or_create(current.id)
    requirement = requirement_service.save_user(
        current.id,
        "旧暗号",
        is_locked=True,
        expected_revision=created.revision,
    )
    characters = CharacterMemoryRepository(project)
    character = characters.create_character("林岚")
    characters.append_state(
        character.id,
        previous.id,
        motivation="追查寄信人",
        psychology="警惕",
        current_goal="核对旧暗号",
        relationships="暂未变化",
        recent_activity="收到来信",
        confidence=1,
        source_type=SourceType.HUMAN,
        review_status=ReviewStatus.APPROVED,
    )
    future_state = characters.append_state(
        character.id,
        future.id,
        motivation="揭晓真相",
        psychology="愤怒",
        current_goal="对质",
        relationships="决裂",
        recent_activity="发现幕后者",
        confidence=1,
        source_type=SourceType.HUMAN,
        review_status=ReviewStatus.APPROVED,
    )
    knowledge = characters.create_knowledge_item(
        "暗号来源", "暗号属于失踪者", Authority.USER_CONFIRMED, ReviewStatus.APPROVED
    )
    character_knowledge = characters.append_knowledge_event(
        knowledge.id,
        KnowledgeSubject.CHARACTER,
        character.id,
        previous.id,
        KnowledgeState.KNOWN,
        "前章认出",
        SourceType.HUMAN,
        ReviewStatus.APPROVED,
    )
    reader_knowledge = characters.append_knowledge_event(
        knowledge.id,
        KnowledgeSubject.READER,
        project.project.id,
        previous.id,
        KnowledgeState.SUSPECTED,
        "读者看到投信背影",
        SourceType.HUMAN,
        ReviewStatus.APPROVED,
    )
    future_knowledge = characters.append_knowledge_event(
        knowledge.id,
        KnowledgeSubject.CHARACTER,
        character.id,
        future.id,
        KnowledgeState.FORGOTTEN,
        "未来失忆",
        SourceType.HUMAN,
        ReviewStatus.APPROVED,
    )
    narrative = NarrativeMemoryRepository(project)
    clue = narrative.add_clue(
        ClueType.FORESHADOW,
        "旧暗号",
        "暗号将指向失踪者",
        Authority.USER_CONFIRMED,
        ReviewStatus.APPROVED,
    )
    narrative.append_clue_action(
        clue.id,
        previous.id,
        ClueAction.PLANT,
        "第一次出现",
        SourceType.HUMAN,
        ReviewStatus.APPROVED,
    )
    future_clue_event = narrative.append_clue_action(
        clue.id,
        future.id,
        ClueAction.RESOLVE,
        "未来揭晓",
        SourceType.HUMAN,
        ReviewStatus.APPROVED,
    )
    styles = StyleRepository(project)
    style = styles.add_rule(
        StyleScope.BOOK,
        project.project.id,
        "叙述声音",
        "克制的近距离第三人称",
        Authority.USER_CONFIRMED,
        ReviewStatus.APPROVED,
    )
    canon = narrative.add_canon(
        "旧暗号",
        "暗号属于失踪者",
        previous.id,
        confidence=1,
        authority=Authority.USER_CONFIRMED,
        review_status=ReviewStatus.APPROVED,
    )
    search = SearchRepository(project)
    search.index_document(
        document_type="CANON",
        source_id=canon.id,
        chapter_id=previous.id,
        title="旧暗号",
        content="旧暗号属于失踪者",
        participants=(character.id,),
        pinned_weight=1,
        review_status=ReviewStatus.APPROVED,
        status=MemoryStatus.CURRENT,
    )
    briefs = ChapterBriefRepository(project)
    provider = BriefContextProvider(
        project,
        requirement_repository,
        characters,
        narrative,
        styles,
        search,
        briefs,
    )
    compiler = ChapterBriefCompiler(provider, briefs)
    return {
        "project": project,
        "chapters": (previous, current, future),
        "requirement": requirement,
        "character": character,
        "character_knowledge": character_knowledge,
        "reader_knowledge": reader_knowledge,
        "future_state": future_state,
        "future_knowledge": future_knowledge,
        "future_clue_event": future_clue_event,
        "clue": clue,
        "style": style,
        "canon": canon,
        "briefs": briefs,
        "provider": provider,
        "compiler": compiler,
    }


def _request(workspace, participants: tuple[str, ...] | None = None):  # type: ignore[no-untyped-def]
    current = workspace["chapters"][1]
    requirement = workspace["requirement"]
    return BriefCompilationRequest(
        chapter_id=current.id,
        mode=CreationMode.STANDARD,
        expected_requirement_revision=requirement.revision,
        target_length=3500,
        story_date="冬至前夜",
        pov_character_id=workspace["character"].id,
        participants=participants or (workspace["character"].id,),
    )


def test_compiler_uses_requirement_first_and_excludes_current_future_evidence(
    tmp_path: Path,
) -> None:
    workspace = _workspace(tmp_path)

    compiled = workspace["compiler"].compile(_request(workspace))
    source_ids = {source.source_id for source in compiled.sources}

    assert compiled.sources[0].source_type == "CHAPTER_REQUIREMENT"
    assert compiled.brief.status == BriefStatus.DRAFT
    assert compiled.brief.dramatic_purpose == "旧暗号"
    assert "人物知识" not in "\n".join(compiled.brief.knowledge)
    assert len(compiled.brief.knowledge) == 1
    assert compiled.brief.knowledge[0].startswith("【读者当前知识摘要】")
    assert workspace["character_knowledge"].id not in source_ids
    assert workspace["reader_knowledge"].id in source_ids
    assert workspace["future_state"].id not in source_ids
    assert workspace["future_knowledge"].id not in source_ids
    assert workspace["future_clue_event"].id not in source_ids
    assert workspace["clue"].id in source_ids
    assert workspace["style"].id in source_ids
    assert workspace["canon"].id in source_ids
    assert all(source.source_hash for source in compiled.sources)


def test_compiler_reports_state_conflict_and_missing_participant_without_guessing(
    tmp_path: Path,
) -> None:
    workspace = _workspace(tmp_path)
    previous = workspace["chapters"][0]
    characters = workspace["provider"].characters
    character = workspace["character"]
    characters.append_state(
        character.id,
        previous.id,
        motivation="另一个动机",
        psychology="恐慌",
        current_goal="逃离",
        relationships="不信任所有人",
        recent_activity="撕毁来信",
        confidence=1,
        source_type=SourceType.HUMAN,
        review_status=ReviewStatus.APPROVED,
    )
    missing = characters.create_character("苏砚")

    compiled = workspace["compiler"].compile(
        _request(workspace, (character.id, missing.id))
    )

    assert {conflict.category for conflict in compiled.conflicts} == {"CHARACTER_STATE"}
    assert any(warning.startswith("CONFLICT:") for warning in compiled.brief.warnings)
    assert any(warning.startswith("MISSING_REQUIRED:") for warning in compiled.brief.warnings)
    with pytest.raises(BriefValidationError, match="缺失|冲突"):
        BriefLifecycleService(workspace["briefs"], workspace["provider"]).freeze(
            compiled.brief.id,
            expected_revision=compiled.brief.revision,
        )


def test_compiler_rejects_stale_requirement_revision(tmp_path: Path) -> None:
    workspace = _workspace(tmp_path)

    with pytest.raises(StaleRequirementError, match="修订"):
        workspace["compiler"].compile(
            BriefCompilationRequest(
                chapter_id=workspace["chapters"][1].id,
                mode=CreationMode.STANDARD,
                expected_requirement_revision=0,
                target_length=3500,
                story_date="",
                pov_character_id=None,
                participants=(workspace["character"].id,),
            )
        )


def test_compiler_reports_equal_authority_canon_conflict_instead_of_choosing(
    tmp_path: Path,
) -> None:
    workspace = _workspace(tmp_path)
    competing = workspace["provider"].narrative.add_canon(
        "旧暗号",
        "暗号属于另一个组织",
        workspace["chapters"][0].id,
        confidence=1,
        authority=Authority.USER_CONFIRMED,
        review_status=ReviewStatus.APPROVED,
    )

    compiled = workspace["compiler"].compile(_request(workspace))

    canon_conflict = next(
        conflict for conflict in compiled.conflicts if conflict.category == "CANON"
    )
    assert set(canon_conflict.source_ids) == {workspace["canon"].id, competing.id}
    assert any(warning.startswith("CONFLICT:") for warning in compiled.brief.warnings)
