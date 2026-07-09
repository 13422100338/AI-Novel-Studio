from pathlib import Path

from ai_novel_studio.application.agent_tool_providers import build_project_agent_registry
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
    character = characters.create_character("林澈")
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

    excerpt = registry.execute(
        AgentToolName.READ_CHAPTER_EXCERPT,
        {"chapter_id": chapter_1.id, "max_chars": 20},
        run_id="run",
        chapter_id=chapter_2.id,
        max_result_chars=50,
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
        {"character_id": character.id, "before_chapter_id": chapter_2.id},
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

    for result in (excerpt, memory, state, knowledge_result, clues, canon, style):
        assert result.content
        assert len(result.content) <= 120
    assert excerpt.source_refs[0].source_id == chapter_1.id
    assert "旧信" in memory.content
    assert "寻找旧信" in state.content
    assert "KNOWN" in knowledge_result.content
    assert "井底旧信" in clues.content
    assert "旧信真实存在" in canon.content
    assert "冷静" in style.content
