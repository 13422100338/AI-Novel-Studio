from pathlib import Path

import pytest

from ai_novel_studio.application.agent_tool_providers import build_project_agent_registry
from ai_novel_studio.application.agent_tools import AgentToolValidationError
from ai_novel_studio.domain.agent import AgentToolName
from ai_novel_studio.domain.memory import (
    Authority,
    ClueAction,
    ClueType,
    KnowledgeState,
    KnowledgeSubject,
    ReviewStatus,
    SourceType,
    StyleScope,
)
from ai_novel_studio.infrastructure.storage.chapter_repository import ChapterRepository
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
    project = ProjectRepository.create(tmp_path / "novel", "Agent Tools")
    chapters = ChapterRepository(project)
    chapter_1 = chapters.create_chapter(
        project.list_volumes()[0].id,
        "Opening",
        "1",
        "旧信被藏在井底。",
    )
    chapter_2 = chapters.create_chapter(
        project.list_volumes()[0].id,
        "Aftermath",
        "2",
        "主角开始追查旧信。",
    )
    return project, chapter_1, chapter_2


def test_project_agent_tools_return_bounded_source_referenced_content(tmp_path: Path) -> None:
    project, chapter_1, chapter_2 = _workspace(tmp_path)
    SearchRepository(project).index_chapter(chapter_1.id, "Opening", "旧信 井底 秘密")
    characters = CharacterMemoryRepository(project)
    character = characters.create_character("林澈", aliases=("阿澈",))
    duplicate = characters.create_character("林澈·温德米尔")
    characters.append_state(
        character.id,
        chapter_1.id,
        motivation="寻找旧信",
        psychology="紧张",
        current_goal="确认信件来源",
        relationships="信任同伴",
        recent_activity="检查井底",
        confidence=1.0,
        source_type=SourceType.HUMAN,
        review_status=ReviewStatus.APPROVED,
    )
    knowledge = characters.create_knowledge_item(
        "旧信",
        "信中提到失踪者。",
        Authority.USER_CONFIRMED,
        ReviewStatus.APPROVED,
    )
    characters.append_knowledge_event(
        knowledge.id,
        KnowledgeSubject.CHARACTER,
        character.id,
        chapter_1.id,
        KnowledgeState.KNOWN,
        "读过信",
        SourceType.HUMAN,
        ReviewStatus.APPROVED,
    )
    narrative = NarrativeMemoryRepository(project)
    narrative.add_canon(
        "旧信",
        "旧信真实存在。",
        chapter_1.id,
        confidence=1.0,
        authority=Authority.USER_CONFIRMED,
        review_status=ReviewStatus.APPROVED,
    )
    clue = narrative.add_clue(
        ClueType.FORESHADOW,
        "井底旧信",
        "后续揭示失踪原因。",
        Authority.USER_CONFIRMED,
        ReviewStatus.APPROVED,
    )
    narrative.append_clue_action(
        clue.id,
        chapter_1.id,
        ClueAction.PLANT,
        "首次埋下旧信",
        SourceType.HUMAN,
        ReviewStatus.APPROVED,
    )
    StyleRepository(project).add_rule(
        StyleScope.BOOK,
        project.project.id,
        "tone",
        "冷静、克制。",
        Authority.USER_CONFIRMED,
        ReviewStatus.APPROVED,
    )

    registry = build_project_agent_registry(project)

    chapter_index = registry.execute(
        AgentToolName.LIST_CHAPTERS,
        {"limit": 10, "offset": 0},
        run_id="run",
        chapter_id=chapter_2.id,
        max_result_chars=500,
    )
    excerpt = registry.execute(
        AgentToolName.READ_CHAPTER_EXCERPT,
        {"chapter_id": chapter_1.id, "max_chars": 20},
        run_id="run",
        chapter_id=chapter_2.id,
        max_result_chars=50,
    )
    batch = registry.execute(
        AgentToolName.READ_CHAPTERS_BATCH,
        {
            "chapter_ids": [chapter_1.id, chapter_2.id],
            "max_chars_per_chapter": 100,
        },
        run_id="run",
        chapter_id=chapter_2.id,
        max_result_chars=500,
    )
    memory = registry.execute(
        AgentToolName.SEARCH_MEMORY,
        {"query": "旧信", "before_chapter_id": chapter_2.id, "limit": 3},
        run_id="run",
        chapter_id=chapter_2.id,
        max_result_chars=120,
    )
    state = registry.execute(
        AgentToolName.GET_CHARACTER_STATE,
        {"character_name": "阿澈", "before_chapter_id": chapter_2.id},
        run_id="run",
        chapter_id=chapter_2.id,
        max_result_chars=120,
    )
    missing_character = registry.execute(
        AgentToolName.GET_CHARACTER_STATE,
        {},
        run_id="run",
        chapter_id=chapter_2.id,
        max_result_chars=120,
    )
    knowledge_result = registry.execute(
        AgentToolName.GET_CHARACTER_KNOWLEDGE,
        {"character_id": character.id, "before_chapter_id": chapter_2.id},
        run_id="run",
        chapter_id=chapter_2.id,
        max_result_chars=120,
    )
    clues = registry.execute(
        AgentToolName.GET_ACTIVE_CLUES,
        {"before_chapter_id": chapter_2.id, "limit": 3},
        run_id="run",
        chapter_id=chapter_2.id,
        max_result_chars=120,
    )
    canon = registry.execute(
        AgentToolName.GET_CANON_FACTS,
        {"query": "旧信", "limit": 3},
        run_id="run",
        chapter_id=chapter_2.id,
        max_result_chars=120,
    )
    style = registry.execute(
        AgentToolName.GET_STYLE_GUIDE,
        {"scope_type": "BOOK", "scope_id": project.project.id, "limit": 3},
        run_id="run",
        chapter_id=chapter_2.id,
        max_result_chars=120,
    )
    identity_proposal = registry.execute(
        AgentToolName.PROPOSE_CHARACTER_IDENTITY_MERGE,
        {
            "source_character_name": character.canonical_name,
            "target_character_name": duplicate.canonical_name,
            "reason": "简称与全称指向同一人物",
        },
        run_id="run",
        chapter_id=chapter_2.id,
        max_result_chars=500,
    )

    for result in (
        chapter_index,
        excerpt,
        batch,
        memory,
        state,
        knowledge_result,
        clues,
        canon,
        style,
    ):
        assert result.content
        assert len(result.content) <= 500
    assert chapter_1.id in chapter_index.content
    assert chapter_2.id in chapter_index.content
    assert "Opening" in chapter_index.content
    assert "Aftermath" in chapter_index.content
    assert excerpt.source_refs[0].source_id == chapter_1.id
    assert [ref.source_id for ref in batch.source_refs] == [
        chapter_1.id,
        chapter_2.id,
    ]
    assert "旧信被藏在井底" in batch.content
    assert "主角开始追查旧信" in batch.content
    assert "旧信" in memory.content
    assert "寻找旧信" in state.content
    assert "character_name" in missing_character.content
    assert "KNOWN" in knowledge_result.content
    assert "井底旧信" in clues.content
    assert "旧信真实存在" in canon.content
    assert "冷静" in style.content
    assert character.id in identity_proposal.content
    assert duplicate.id in identity_proposal.content
    assert "需要用户确认" in identity_proposal.content
    assert [ref.source_id for ref in identity_proposal.source_refs] == [
        character.id,
        duplicate.id,
    ]

    with pytest.raises(AgentToolValidationError, match="同一张人物卡"):
        registry.execute(
            AgentToolName.PROPOSE_CHARACTER_IDENTITY_MERGE,
            {
                "source_character_name": character.canonical_name,
                "target_character_name": character.canonical_name,
                "reason": "错误的自身归并提案",
            },
            run_id="run",
            chapter_id=chapter_2.id,
            max_result_chars=500,
        )


def test_batch_chapter_reader_covers_a_full_small_novel_in_one_call(
    tmp_path: Path,
) -> None:
    project = ProjectRepository.create(tmp_path / "novel", "Batch Reader")
    chapters = ChapterRepository(project)
    volume_id = project.list_volumes()[0].id
    created = tuple(
        chapters.create_chapter(
            volume_id,
            f"Chapter {index}",
            str(index),
            f"第{index}章正文。" + ("情节内容" * 80),
        )
        for index in range(1, 35)
    )
    registry = build_project_agent_registry(project)

    result = registry.execute(
        AgentToolName.READ_CHAPTERS_BATCH,
        {
            "chapter_ids": [chapter.id for chapter in created],
            "max_chars_per_chapter": 600,
        },
        run_id="run",
        chapter_id=created[-1].id,
        max_result_chars=16_000,
    )

    assert len(result.source_refs) == 34
    assert [ref.source_id for ref in result.source_refs] == [
        chapter.id for chapter in created
    ]
    assert "第1章正文" in result.content
    assert "第34章正文" in result.content
    assert len(result.content) <= 16_000
