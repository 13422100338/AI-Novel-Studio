from pathlib import Path

from pytest import MonkeyPatch

from ai_novel_studio.application.project_memory_workspace_gateway import (
    ProjectMemoryWorkspaceGateway,
)
from ai_novel_studio.domain.memory import (
    Authority,
    ClueAction,
    ClueType,
    KnowledgeState,
    KnowledgeSubject,
    ReviewStatus,
    SourceType,
    StyleScope,
    SummaryLevel,
)
from ai_novel_studio.infrastructure.storage.chapter_repository import ChapterRepository
from ai_novel_studio.infrastructure.storage.character_memory_repository import (
    CharacterMemoryRepository,
)
from ai_novel_studio.infrastructure.storage.narrative_memory_repository import (
    NarrativeMemoryRepository,
)
from ai_novel_studio.infrastructure.storage.project_repository import ProjectRepository
from ai_novel_studio.infrastructure.storage.style_repository import StyleRepository
from ai_novel_studio.infrastructure.storage.summary_repository import SummaryRepository


def test_gateway_exposes_summary_candidates_for_memory_window(tmp_path: Path) -> None:
    project = ProjectRepository.create(tmp_path / "novel", "Novel")
    volume = project.list_volumes()[0]
    chapter = ChapterRepository(project).create_chapter(volume.id, "Opening", "1", "body")
    summary = SummaryRepository(project).add_candidate(
        SummaryLevel.CHAPTER,
        chapter.id,
        "候选摘要",
        (chapter.id,),
        model_profile_id="local-import-baseline",
    )
    gateway = ProjectMemoryWorkspaceGateway(project)

    records = gateway.load_before("__all__")
    updated = gateway.update_content(summary.id, "人工修订摘要", expected_revision=0)
    promoted = gateway.promote(summary.id, expected_revision=1)

    assert records[0].category == "压缩前文"
    assert records[0].title == "章节摘要（待模型升级）：Opening"
    assert records[0].source_type == "SUMMARY_FALLBACK"
    assert records[0].content == "候选摘要"
    assert records[0].promotable is False
    assert updated.content == "人工修订摘要"
    assert promoted.review_status == ReviewStatus.APPROVED


def test_gateway_exposes_character_state_candidates_for_memory_window(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    project = ProjectRepository.create(tmp_path / "novel", "Novel")
    volume = project.list_volumes()[0]
    chapter = ChapterRepository(project).create_chapter(
        volume.id, "Opening", "1", "林默收到匿名旧信。"
    )
    characters = CharacterMemoryRepository(project)
    character = characters.create_character("林默")
    characters.append_state(
        character.id,
        chapter.id,
        motivation="确认旧信真伪",
        psychology="警惕",
        current_goal="去旧港档案室",
        relationships="不信任来信者",
        recent_activity="收到匿名旧信",
        confidence=0.8,
        source_type=SourceType.MODEL,
        review_status=ReviewStatus.REVIEW,
    )
    gateway = ProjectMemoryWorkspaceGateway(project)

    records = gateway.load_before("__all__")
    character_records = [record for record in records if record.category == "人物状态"]

    assert len(character_records) == 1
    assert character_records[0].title == "人物状态：林默 / Opening"
    assert "心理：警惕" in character_records[0].content
    assert "目标：去旧港档案室" in character_records[0].content
    assert character_records[0].editable is True
    assert character_records[0].promotable is True

    with monkeypatch.context() as patch:
        patch.setattr(
            gateway,
            "load_before",
            lambda _chapter_id: (_ for _ in ()).throw(
                AssertionError("structured promotion must not reload the full workspace")
            ),
        )
        promoted = gateway.promote(character_records[0].id, expected_revision=0)

    assert promoted.review_status == ReviewStatus.APPROVED
    assert promoted.promotable is False

    updated = gateway.update_fields(
        character_records[0].id,
        "CHARACTER_STATE",
        {
            "motivation": "查明旧信来源",
            "psychology": "警惕但坚定",
            "current_goal": "进入旧港档案室",
            "relationships": "",
            "recent_activity": "",
        },
        expected_revision=0,
    )

    assert updated.review_status == ReviewStatus.APPROVED
    assert updated.authority == Authority.USER_CONFIRMED
    assert "心理：警惕但坚定" in updated.content


def test_gateway_exposes_canon_clues_knowledge_and_style_tabs(tmp_path: Path) -> None:
    project = ProjectRepository.create(tmp_path / "novel", "Novel")
    volume = project.list_volumes()[0]
    chapter = ChapterRepository(project).create_chapter(volume.id, "Opening", "1", "body")
    narrative = NarrativeMemoryRepository(project)
    narrative.add_canon(
        "旧港规则",
        "午夜后档案室关闭。",
        chapter.id,
        confidence=0.8,
        authority=Authority.MODEL_EXTRACTED,
        review_status=ReviewStatus.REVIEW,
    )
    clue = narrative.add_clue(
        ClueType.FORESHADOW,
        "潮湿指纹",
        "与失踪兄长有关。",
        Authority.MODEL_EXTRACTED,
        ReviewStatus.REVIEW,
    )
    narrative.append_clue_action(
        clue.id,
        chapter.id,
        ClueAction.PLANT,
        "首次出现",
        SourceType.MODEL,
        ReviewStatus.REVIEW,
    )
    characters = CharacterMemoryRepository(project)
    character = characters.create_character("林默")
    knowledge = characters.create_knowledge_item(
        "暗号来源", "暗号属于兄长。", Authority.MODEL_EXTRACTED, ReviewStatus.REVIEW
    )
    characters.append_knowledge_event(
        knowledge.id,
        KnowledgeSubject.CHARACTER,
        character.id,
        chapter.id,
        KnowledgeState.KNOWN,
        "本章认出",
        SourceType.MODEL,
        ReviewStatus.REVIEW,
    )
    StyleRepository(project).add_rule(
        StyleScope.CHAPTER,
        chapter.id,
        "节奏",
        "使用短句。",
        Authority.MODEL_EXTRACTED,
        ReviewStatus.REVIEW,
    )

    gateway = ProjectMemoryWorkspaceGateway(project)
    records = gateway.load_before("__all__")
    categories = {record.category for record in records}

    assert {"正典事实", "伏笔与叙事线索", "人物知识", "文风候选"} <= categories

    by_category = {record.category: record for record in records}
    updates = {
        "正典事实": {
            "title": "旧港档案室规则",
            "detail": "午夜后档案室必须关闭。",
        },
        "伏笔与叙事线索": {
            "clue_type": ClueType.FORESHADOW.value,
            "title": "潮湿的指纹",
            "clue_detail": "可能与失踪兄长有关。",
            "action": ClueAction.REINFORCE.value,
            "event_detail": "",
        },
        "人物知识": {
            "title": "暗号的来源",
            "detail": "暗号属于失踪的兄长。",
            "state": KnowledgeState.SUSPECTED.value,
            "evidence": "",
        },
        "文风候选": {
            "scope_type": StyleScope.CHAPTER.value,
            "scope_id": chapter.id,
            "rule_type": "动作节奏",
            "rule_text": "动作场景优先使用短句。",
        },
    }
    for category, fields in updates.items():
        record = by_category[category]
        updated = gateway.update_fields(record.id, record.source_type, fields, expected_revision=0)
        assert updated.review_status == ReviewStatus.APPROVED
        assert updated.authority == Authority.USER_CONFIRMED
