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
    MemoryStatus,
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
from ai_novel_studio.infrastructure.storage.summary_repository import (
    MODEL_RETRY_PROFILE_ID,
    SummaryRepository,
)


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


def test_gateway_labels_stale_fallback_as_read_only_historical_version(
    tmp_path: Path,
) -> None:
    project = ProjectRepository.create(tmp_path / "novel", "Novel")
    volume = project.list_volumes()[0]
    chapters = ChapterRepository(project)
    chapter = chapters.create_chapter(volume.id, "Opening", "1", "old body")
    summary = SummaryRepository(project).add_candidate(
        SummaryLevel.CHAPTER,
        chapter.id,
        "旧保底摘要",
        (chapter.id,),
        model_profile_id="local-import-baseline",
    )
    chapters.save_content(
        chapter.id,
        "rewritten body",
        source="manual",
        reason="rewrite",
    )

    record = next(
        item
        for item in ProjectMemoryWorkspaceGateway(project).load_before("__all__")
        if item.id == summary.id
    )

    assert record.title == "章节摘要（历史版本）：Opening"
    assert record.source_type == "SUMMARY_HISTORY"
    assert record.status == MemoryStatus.STALE
    assert record.editable is False
    assert record.promotable is False


def test_gateway_can_undo_model_summary_promotion_for_a_targeted_retry(
    tmp_path: Path,
) -> None:
    project = ProjectRepository.create(tmp_path / "novel", "Novel")
    volume = project.list_volumes()[0]
    chapter = ChapterRepository(project).create_chapter(volume.id, "Opening", "1", "body")
    repository = SummaryRepository(project)
    summary = repository.add_candidate(
        SummaryLevel.CHAPTER,
        chapter.id,
        "Model summary",
        (chapter.id,),
        model_profile_id="memory-model",
    )
    promoted = repository.promote(summary.id, expected_revision=0)
    gateway = ProjectMemoryWorkspaceGateway(project)
    gateway.load_before("__all__")

    retried = gateway.request_model_retry(summary.id, expected_revision=promoted.revision)
    stored = repository.get(summary.id)

    assert retried.source_type == "SUMMARY_FALLBACK"
    assert retried.review_status == ReviewStatus.REVIEW
    assert retried.promotable is False
    assert stored.model_profile_id == MODEL_RETRY_PROFILE_ID
    assert stored.content == "Model summary"


def test_manual_summary_edit_cannot_be_replaced_by_retry(tmp_path: Path) -> None:
    project = ProjectRepository.create(tmp_path / "novel", "Novel")
    volume = project.list_volumes()[0]
    chapter = ChapterRepository(project).create_chapter(volume.id, "Opening", "1", "body")
    repository = SummaryRepository(project)
    summary = repository.add_candidate(
        SummaryLevel.CHAPTER,
        chapter.id,
        "Model summary",
        (chapter.id,),
        model_profile_id="memory-model",
    )
    gateway = ProjectMemoryWorkspaceGateway(project)
    gateway.load_before("__all__")
    edited = gateway.update_content(summary.id, "Human correction", expected_revision=0)
    promoted = gateway.promote(summary.id, expected_revision=edited.revision)

    try:
        gateway.request_model_retry(summary.id, expected_revision=promoted.revision)
    except PermissionError:
        pass
    else:
        raise AssertionError("human-confirmed summaries must reject model retry")

    stored = repository.get(summary.id)
    assert stored.authority == Authority.USER_CONFIRMED
    assert stored.model_profile_id is None
    assert stored.content == "Human correction"


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
    characters.update_character_profile(character.id, "克制寡言，紧张时会摩挲袖口。")
    first_state = characters.append_state(
        character.id,
        chapter.id,
        motivation="确认旧信真伪",
        psychology="警惕",
        current_goal="去旧港档案室",
        relationships="不信任来信者",
        recent_activity="收到匿名旧信",
        confidence=0.8,
        source_type=SourceType.MODEL,
        review_status=ReviewStatus.APPROVED,
    )
    later_chapter = ChapterRepository(project).create_chapter(
        volume.id, "Archive", "2", "林默进入档案室。"
    )
    second_state = characters.append_state(
        character.id,
        later_chapter.id,
        motivation="查明旧信来源",
        psychology="警惕但坚定",
        current_goal="进入旧港档案室",
        relationships="开始相信守门人",
        recent_activity="抵达旧港档案室",
        confidence=0.9,
        source_type=SourceType.MODEL,
        review_status=ReviewStatus.REVIEW,
    )
    gateway = ProjectMemoryWorkspaceGateway(project)

    records = gateway.load_before("__all__")
    character_records = [record for record in records if record.category == "人物状态"]

    assert len(character_records) == 1
    assert character_records[0].id == f"character-card:{character.id}"
    assert character_records[0].source_type == "CHARACTER_CARD"
    assert character_records[0].title == "人物状态：林默"
    assert "性格、语言与动作特点：克制寡言" in character_records[0].content
    assert "当前心理与目标：警惕但坚定；进入旧港档案室" in character_records[0].content
    assert "过往心路历程" in character_records[0].content
    assert "Opening" in character_records[0].content
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
    assert characters.state_history(character.id)[0].id == first_state.id
    assert characters.state_history(character.id)[1].id == second_state.id
    assert all(
        event.review_status == ReviewStatus.APPROVED
        for event in characters.state_history(character.id)
    )

    updated = gateway.update_fields(
        character_records[0].id,
        "CHARACTER_CARD",
        {
            "profile": "谨慎寡言，思考时摩挲袖口。",
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
    assert "当前心理与目标：警惕但坚定；进入旧港档案室" in updated.content
    assert characters.get_character(character.id).profile == "谨慎寡言，思考时摩挲袖口。"
    latest = characters.state_history(character.id)[-1]
    assert latest.id == second_state.id
    assert latest.source_type == SourceType.HUMAN


def test_gateway_exposes_active_memory_tabs_and_hides_retired_style_candidates(
    tmp_path: Path,
) -> None:
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
    reader_first = characters.create_knowledge_item(
        "来信来源", "读者看见来信来自钟楼。", Authority.MODEL_EXTRACTED, ReviewStatus.REVIEW
    )
    characters.append_knowledge_event(
        reader_first.id,
        KnowledgeSubject.READER,
        project.project.id,
        chapter.id,
        KnowledgeState.KNOWN,
        "正文证据",
        SourceType.MODEL,
        ReviewStatus.REVIEW,
    )
    reader_second = characters.create_knowledge_item(
        "兄长下落", "读者怀疑兄长仍然活着。", Authority.MODEL_EXTRACTED, ReviewStatus.REVIEW
    )
    characters.append_knowledge_event(
        reader_second.id,
        KnowledgeSubject.READER,
        project.project.id,
        chapter.id,
        KnowledgeState.SUSPECTED,
        "正文证据",
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

    assert {"正典事实", "伏笔与叙事线索", "读者知识"} <= categories
    assert "文风候选" not in categories
    assert "人物知识" not in categories
    assert sum(record.category == "读者知识" for record in records) == 1

    by_category = {record.category: record for record in records}
    assert by_category["正典事实"].group_key == "WORLD"
    updates = {
        "正典事实": {
            "title": "旧港档案室规则",
            "detail": "午夜后档案室必须关闭。",
            "category": "重要物品、能力与兵器",
        },
        "伏笔与叙事线索": {
            "clue_type": ClueType.FORESHADOW.value,
            "title": "潮湿的指纹",
            "clue_detail": "可能与失踪兄长有关。",
            "action": ClueAction.REINFORCE.value,
            "event_detail": "",
        },
        "读者知识": {
            "detail": "读者知道来信来自钟楼，并怀疑兄长仍然活着。",
        },
    }
    for category, fields in updates.items():
        record = by_category[category]
        updated = gateway.update_fields(record.id, record.source_type, fields, expected_revision=0)
        assert updated.review_status == ReviewStatus.APPROVED
        assert updated.authority == Authority.USER_CONFIRMED
        if category == "正典事实":
            assert updated.group_key == "ITEM_ABILITY"
            category_field = next(field for field in updated.fields if field.key == "category")
            assert category_field.value == "重要物品、能力与兵器"
        if category == "读者知识":
            assert updated.content == "读者知道来信来自钟楼，并怀疑兄长仍然活着。"

    reloaded_reader = next(
        record
        for record in gateway.load_before("__all__")
        if record.category == "读者知识"
    )
    assert reloaded_reader.content == "读者知道来信来自钟楼，并怀疑兄长仍然活着。"
