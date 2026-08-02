import hashlib
from pathlib import Path

from ai_novel_studio.application.canon_card_context_service import (
    CanonCardCategory,
    CanonCardContextService,
)
from ai_novel_studio.application.chapter_context_pin_service import (
    ChapterContextPinService,
)
from ai_novel_studio.application.character_card_context_service import (
    CharacterCardContextService,
)
from ai_novel_studio.application.generation_context_service import (
    GenerationContextService,
    GenerationPreparationRequest,
)
from ai_novel_studio.application.generation_memory_context_provider import (
    GenerationMemoryContextProvider,
)
from ai_novel_studio.application.plot_memory_context_service import (
    PlotMemoryContextService,
)
from ai_novel_studio.application.project_memory_workspace_gateway import (
    ProjectMemoryWorkspaceGateway,
)
from ai_novel_studio.application.reader_knowledge_summary_service import (
    ReaderKnowledgeSummaryService,
)
from ai_novel_studio.application.view_assertion_service import ViewAssertionService
from ai_novel_studio.core.context.context_builder import (
    ContextBuilder,
    ContextBuildRequest,
)
from ai_novel_studio.core.context.context_manifest import ContextManifestRepository
from ai_novel_studio.core.context.token_budget import TokenBudget
from ai_novel_studio.core.memory.narrative_clue_ledger import NarrativeClueLedger
from ai_novel_studio.domain.generation import CreationMode
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
from ai_novel_studio.domain.view import ViewAssertionDraft, ViewType
from ai_novel_studio.infrastructure.llm import ModelCapabilities
from ai_novel_studio.infrastructure.storage.chapter_brief_repository import (
    ChapterBriefRepository,
)
from ai_novel_studio.infrastructure.storage.chapter_context_pin_repository import (
    ChapterContextPinRepository,
)
from ai_novel_studio.infrastructure.storage.chapter_repository import ChapterRepository
from ai_novel_studio.infrastructure.storage.chapter_requirement_repository import (
    ChapterRequirementRepository,
)
from ai_novel_studio.infrastructure.storage.character_memory_repository import (
    CharacterMemoryRepository,
)
from ai_novel_studio.infrastructure.storage.generation_repository import GenerationRepository
from ai_novel_studio.infrastructure.storage.narrative_memory_repository import (
    NarrativeMemoryRepository,
)
from ai_novel_studio.infrastructure.storage.project_repository import ProjectRepository
from ai_novel_studio.infrastructure.storage.search_repository import SearchRepository
from ai_novel_studio.infrastructure.storage.style_repository import StyleRepository
from ai_novel_studio.infrastructure.storage.summary_repository import SummaryRepository


def _project_with_stale_and_current_history(
    tmp_path: Path,
) -> tuple[ProjectRepository, ChapterRepository, str, str, str]:
    project = ProjectRepository.create(tmp_path / "novel", "Novel")
    volume = project.list_volumes()[0]
    chapters = ChapterRepository(project)
    stale_source = chapters.create_chapter(
        volume.id,
        "Old Archive",
        "1",
        "forgotten vault clue STALE_HISTORY_MARKER",
    )
    current_source = chapters.create_chapter(
        volume.id,
        "Current Archive",
        "2",
        "forgotten vault clue CURRENT_HISTORY_MARKER",
    )
    target = chapters.create_chapter(volume.id, "Target", "3")
    search = SearchRepository(project)
    search.index_chapter(
        stale_source.id,
        "STALE_HISTORY_MARKER",
        "forgotten vault clue STALE_HISTORY_MARKER",
    )
    search.index_chapter(
        current_source.id,
        "CURRENT_HISTORY_MARKER",
        "forgotten vault clue CURRENT_HISTORY_MARKER",
    )
    chapters.save_content(
        stale_source.id,
        "The old archive was rewritten without the retired evidence.",
        source="manual",
        reason="story rewrite",
    )
    return project, chapters, stale_source.id, current_source.id, target.id


def test_history_blocks_map_only_authoritative_stale_status(
    tmp_path: Path,
) -> None:
    project, _chapters, stale_source_id, current_source_id, target_id = (
        _project_with_stale_and_current_history(tmp_path)
    )

    blocks = GenerationMemoryContextProvider(project).blocks(
        target_id,
        "forgotten vault clue",
        (),
    )
    stale = next(
        block
        for block in blocks
        if block.source_type == "HISTORY_CHAPTER"
        and block.source_id == stale_source_id
    )
    current = next(
        block
        for block in blocks
        if block.source_type == "HISTORY_CHAPTER"
        and block.source_id == current_source_id
    )

    assert current.eligibility.stale is False
    assert stale.eligibility.stale is True


def test_stale_history_is_manifested_but_never_reaches_writer_prompt(
    tmp_path: Path,
) -> None:
    project, chapters, stale_source_id, current_source_id, target_id = (
        _project_with_stale_and_current_history(tmp_path)
    )
    requirements = ChapterRequirementRepository(project)
    initial = requirements.get_or_create(target_id)
    requirements.update(
        target_id,
        "Continue from the forgotten vault clue.",
        is_locked=True,
        expected_revision=initial.revision,
    )
    service = GenerationContextService(
        project,
        chapters,
        requirements,
        ChapterBriefRepository(project),
        GenerationRepository(project),
        ContextManifestRepository(project),
    )

    prepared = service.prepare(
        GenerationPreparationRequest(
            chapter_id=target_id,
            mode=CreationMode.BASIC,
            brief_id=None,
            output_token_limit=2_000,
            model_capabilities=ModelCapabilities(
                context_window=32_000,
                max_output_tokens=4_000,
            ),
            target_words=1_000,
            model_provider_id="provider",
            model_id="writer",
        )
    )

    assert any(
        item.source_type == "HISTORY_CHAPTER"
        and item.source_id == current_source_id
        for item in prepared.manifest.selected
    )
    stale_omission = next(
        (
            item
            for item in prepared.manifest.omitted
            if item.source_type == "HISTORY_CHAPTER"
            and item.source_id == stale_source_id
        ),
        None,
    )
    writer_prompt = "\n".join(message.content for message in prepared.messages)
    stale_selected = any(
        item.source_type == "HISTORY_CHAPTER"
        and item.source_id == stale_source_id
        for item in prepared.manifest.selected
    )

    assert stale_omission is not None, (
        f"stale_selected={stale_selected}, "
        f"stale_in_writer_prompt={'STALE_HISTORY_MARKER' in writer_prompt}"
    )
    assert stale_omission.reason == "HARD_FILTER:STALE"
    assert "STALE_HISTORY_MARKER" not in writer_prompt
    assert "CURRENT_HISTORY_MARKER" in writer_prompt


def test_unapproved_style_rules_are_manifested_but_never_reach_writer_prompt(
    tmp_path: Path,
) -> None:
    project = ProjectRepository.create(tmp_path / "novel", "Novel")
    volume = project.list_volumes()[0]
    chapters = ChapterRepository(project)
    target = chapters.create_chapter(volume.id, "Target", "1")
    requirements = ChapterRequirementRepository(project)
    initial = requirements.get_or_create(target.id)
    requirements.update(
        target.id,
        "Continue the scene.",
        is_locked=True,
        expected_revision=initial.revision,
    )
    styles = StyleRepository(project)
    approved = styles.add_rule(
        StyleScope.BOOK,
        project.project.id,
        "approved",
        "APPROVED_STYLE_MARKER",
        Authority.USER_CONFIRMED,
        ReviewStatus.APPROVED,
    )
    review = styles.add_rule(
        StyleScope.BOOK,
        project.project.id,
        "review",
        "REVIEW_STYLE_MARKER",
        Authority.MODEL_EXTRACTED,
        ReviewStatus.REVIEW,
    )
    rejected = styles.add_rule(
        StyleScope.BOOK,
        project.project.id,
        "rejected",
        "REJECTED_STYLE_MARKER",
        Authority.MODEL_EXTRACTED,
        ReviewStatus.REJECTED,
    )
    service = GenerationContextService(
        project,
        chapters,
        requirements,
        ChapterBriefRepository(project),
        GenerationRepository(project),
        ContextManifestRepository(project),
    )

    style_blocks = tuple(
        block
        for block in service.memory_context.blocks(
            target.id,
            "Continue the scene.",
            (),
        )
        if block.source_type == "STYLE_RULE"
    )

    assert next(block for block in style_blocks if block.source_id == approved.id).priority == 20
    assert {
        block.source_id
        for block in style_blocks
        if not block.eligibility.authority_allowed
    } == {review.id, rejected.id}

    prepared = service.prepare(
        GenerationPreparationRequest(
            chapter_id=target.id,
            mode=CreationMode.BASIC,
            brief_id=None,
            output_token_limit=2_000,
            model_capabilities=ModelCapabilities(
                context_window=32_000,
                max_output_tokens=4_000,
            ),
            target_words=1_000,
            model_provider_id="provider",
            model_id="writer",
        )
    )

    assert any(item.source_id == approved.id for item in prepared.manifest.selected)
    omissions = {
        item.source_id: item.reason
        for item in prepared.manifest.omitted
        if item.source_type == "STYLE_RULE"
    }
    assert omissions == {
        review.id: "HARD_FILTER:AUTHORITY_REJECTED",
        rejected.id: "HARD_FILTER:AUTHORITY_REJECTED",
    }
    writer_prompt = "\n".join(message.content for message in prepared.messages)
    assert "APPROVED_STYLE_MARKER" in writer_prompt
    assert "REVIEW_STYLE_MARKER" not in writer_prompt
    assert "REJECTED_STYLE_MARKER" not in writer_prompt


def test_unapproved_style_samples_are_manifested_without_loading_candidate_bodies(
    tmp_path: Path,
) -> None:
    project = ProjectRepository.create(tmp_path / "novel", "Novel")
    volume = project.list_volumes()[0]
    chapters = ChapterRepository(project)
    target = chapters.create_chapter(volume.id, "Target", "1")
    requirements = ChapterRequirementRepository(project)
    initial = requirements.get_or_create(target.id)
    requirements.update(
        target.id,
        "Continue the scene.",
        is_locked=True,
        expected_revision=initial.revision,
    )
    styles = StyleRepository(project)
    approved = styles.add_sample(
        StyleScope.BOOK,
        project.project.id,
        "approved",
        "APPROVED_SAMPLE_MARKER",
        SourceType.HUMAN,
        Authority.USER_CONFIRMED,
        ReviewStatus.APPROVED,
        immutable=False,
    )
    review = styles.add_sample(
        StyleScope.BOOK,
        project.project.id,
        "review",
        "REVIEW_SAMPLE_SECRET_MARKER",
        SourceType.MODEL,
        Authority.MODEL_EXTRACTED,
        ReviewStatus.REVIEW,
        immutable=False,
    )
    rejected = styles.add_sample(
        StyleScope.CHAPTER,
        target.id,
        "rejected",
        "REJECTED_SAMPLE_SECRET_MARKER",
        SourceType.MODEL,
        Authority.MODEL_EXTRACTED,
        ReviewStatus.REJECTED,
        immutable=False,
    )
    service = GenerationContextService(
        project,
        chapters,
        requirements,
        ChapterBriefRepository(project),
        GenerationRepository(project),
        ContextManifestRepository(project),
    )

    style_blocks = tuple(
        block
        for block in service.memory_context.blocks(
            target.id,
            "Continue the scene.",
            (),
        )
        if block.source_type == "STYLE_SAMPLE"
    )

    assert next(block for block in style_blocks if block.source_id == approved.id).content == (
        "人工样章/approved：\nAPPROVED_SAMPLE_MARKER"
    )
    candidate_blocks = {
        block.source_id: block
        for block in style_blocks
        if not block.eligibility.authority_allowed
    }
    assert set(candidate_blocks) == {review.id, rejected.id}
    assert {
        block.content for block in candidate_blocks.values()
    } == {"未通过审查的文风样章候选"}
    assert candidate_blocks[review.id].source_hash == review.content_hash
    assert candidate_blocks[rejected.id].source_hash == rejected.content_hash
    assert all(block.source_revision is None for block in candidate_blocks.values())

    prepared = service.prepare(
        GenerationPreparationRequest(
            chapter_id=target.id,
            mode=CreationMode.BASIC,
            brief_id=None,
            output_token_limit=2_000,
            model_capabilities=ModelCapabilities(
                context_window=32_000,
                max_output_tokens=4_000,
            ),
            target_words=1_000,
            model_provider_id="provider",
            model_id="writer",
        )
    )

    assert any(item.source_id == approved.id for item in prepared.manifest.selected)
    omissions = {
        item.source_id: item.reason
        for item in prepared.manifest.omitted
        if item.source_type == "STYLE_SAMPLE"
    }
    assert omissions == {
        review.id: "HARD_FILTER:AUTHORITY_REJECTED",
        rejected.id: "HARD_FILTER:AUTHORITY_REJECTED",
    }
    writer_prompt = "\n".join(message.content for message in prepared.messages)
    assert "APPROVED_SAMPLE_MARKER" in writer_prompt
    assert "REVIEW_SAMPLE_SECRET_MARKER" not in writer_prompt
    assert "REJECTED_SAMPLE_SECRET_MARKER" not in writer_prompt


def test_plot_keeps_legacy_card_while_prose_uses_physical_writer_projection(
    tmp_path: Path,
) -> None:
    project = ProjectRepository.create(tmp_path / "novel", "Novel")
    volume = project.list_volumes()[0]
    chapters = ChapterRepository(project)
    prologue = chapters.create_chapter(volume.id, "Prologue", "1", "A storm hit the town.")
    first = chapters.create_chapter(volume.id, "Opening", "2", "Eric found a letter.")
    current = chapters.create_chapter(volume.id, "Visit", "3", "Current draft")
    memory = CharacterMemoryRepository(project)
    eric = memory.create_character(
        "Eric Windermere",
        ("Eric",),
        "Restrained voice; rubs his cuff when anxious.",
    )
    for chapter_id, psychology, goal, location, injury_status in (
        (prologue.id, "Afraid", "Survive the storm", "Town square", ""),
        (
            first.id,
            "Guarded",
            "Find the letter's sender",
            "Old harbor",
            "Bandaged right hand",
        ),
        (
            current.id,
            "Angry",
            "Confront the sender",
            "CURRENT_LOCATION_SECRET",
            "CURRENT_INJURY_SECRET",
        ),
    ):
        memory.append_state(
            eric.id,
            chapter_id,
            motivation="Protect the town",
            psychology=psychology,
            current_goal=goal,
            relationships="Cautiously trusts Alice",
            recent_activity=f"Working to {goal}",
            location=location,
            injury_status=injury_status,
            confidence=1,
            source_type=SourceType.HUMAN,
            review_status=ReviewStatus.APPROVED,
        )
    review = memory.append_state(
        eric.id,
        first.id,
        motivation="REVIEW_STATE_SECRET_MOTIVATION",
        psychology="REVIEW_STATE_SECRET_PSYCHOLOGY",
        current_goal="REVIEW_STATE_SECRET_GOAL",
        relationships="REVIEW_STATE_SECRET_RELATIONSHIPS",
        recent_activity="REVIEW_STATE_SECRET_RECENT",
        location="REVIEW_LOCATION_SECRET",
        injury_status="REVIEW_INJURY_SECRET",
        confidence=0.8,
        source_type=SourceType.MODEL,
        review_status=ReviewStatus.REVIEW,
    )
    current_review = memory.append_state(
        eric.id,
        current.id,
        motivation="CURRENT_REVIEW_STATE_SECRET",
        psychology="",
        current_goal="",
        relationships="",
        recent_activity="",
        location="CURRENT_REVIEW_LOCATION_SECRET",
        injury_status="CURRENT_REVIEW_INJURY_SECRET",
        confidence=0.8,
        source_type=SourceType.MODEL,
        review_status=ReviewStatus.REVIEW,
    )

    shared = CharacterCardContextService(project).items_before(current.id)
    plot = PlotMemoryContextService(project).select(current.id, token_budget=6_000)
    prose_blocks = GenerationMemoryContextProvider(project).blocks(
        current.id,
        "Eric visits Alice.",
        (),
    )

    assert len(shared) == 1
    assert plot.message is not None
    assert plot.message.content.count(shared[0].content) == 1
    writer_block = next(
        block
        for block in prose_blocks
        if block.source_type == "CHARACTER_STATE"
        and block.eligibility.authority_allowed
    )
    assert writer_block.content != shared[0].content
    assert "当前位置：Old harbor" in writer_block.content
    assert "伤势状态：Bandaged right hand" in writer_block.content
    assert writer_block.content.index("当前动机：") < writer_block.content.index(
        "当前位置："
    )
    assert writer_block.content.index("当前位置：") < writer_block.content.index(
        "伤势状态："
    )
    assert writer_block.content.index("伤势状态：") < writer_block.content.index(
        "人物关系："
    )
    assert writer_block.source_hash == hashlib.sha256(
        writer_block.content.encode("utf-8")
    ).hexdigest()
    assert "Old harbor" not in shared[0].content
    assert "Bandaged right hand" not in shared[0].content
    assert "Old harbor" not in plot.message.content
    assert "Bandaged right hand" not in plot.message.content
    candidate = next(
        block
        for block in prose_blocks
        if block.source_type == "CHARACTER_STATE" and block.source_id == review.id
    )
    assert candidate.content == "未通过审查的人物状态候选"
    assert candidate.rationale == "未通过审查的人物状态候选"
    assert candidate.source_chapter_id == first.id
    assert candidate.source_revision is None
    assert candidate.source_hash == hashlib.sha256(
        "\x1f".join(
            (
                review.motivation,
                review.psychology,
                review.current_goal,
                review.relationships,
                review.recent_activity,
            )
        ).encode()
    ).hexdigest()
    assert candidate.eligibility.authority_allowed is False
    assert review.current_goal not in candidate.content
    assert all(block.source_id != current_review.id for block in prose_blocks)
    built = ContextBuilder().build(
        ContextBuildRequest(
            chapter_id=current.id,
            run_id="character-review-filter",
            budget=TokenBudget(20_000, 2_000, 0),
            blocks=prose_blocks,
            deduplicate=True,
        )
    )
    omission = next(
        item
        for item in built.manifest.omitted
        if item.source_type == "CHARACTER_STATE" and item.source_id == review.id
    )
    assert omission.reason == "HARD_FILTER:AUTHORITY_REJECTED"
    assert omission.source_revision is None
    assert not hasattr(omission, "motivation")
    assert not hasattr(omission, "current_goal")
    assert review.motivation not in built.text
    assert review.current_goal not in built.text
    assert current_review.motivation not in built.text
    assert review.motivation not in plot.message.content
    for forbidden in (
        "REVIEW_LOCATION_SECRET",
        "REVIEW_INJURY_SECRET",
        "CURRENT_LOCATION_SECRET",
        "CURRENT_INJURY_SECRET",
        "CURRENT_REVIEW_LOCATION_SECRET",
        "CURRENT_REVIEW_INJURY_SECRET",
    ):
        assert forbidden not in writer_block.content
        assert forbidden not in built.text
        assert forbidden not in plot.message.content
    assert "Restrained voice; rubs his cuff when anxious." in shared[0].content
    assert "Survive the storm" in shared[0].content
    past_journey = shared[0].content.split("过往心路历程：", maxsplit=1)[1]
    assert "Find the letter's sender" not in past_journey
    assert "Confront the sender" not in shared[0].content


def test_prose_context_does_not_reinject_retired_character_knowledge(
    tmp_path: Path,
) -> None:
    project = ProjectRepository.create(tmp_path / "novel", "Novel")
    volume = project.list_volumes()[0]
    chapters = ChapterRepository(project)
    first = chapters.create_chapter(volume.id, "Opening", "1", "Eric found a letter.")
    current = chapters.create_chapter(volume.id, "Visit", "2", "")
    memory = CharacterMemoryRepository(project)
    eric = memory.create_character("Eric")
    memory.append_state(
        eric.id,
        first.id,
        motivation="Protect Alice",
        psychology="Guarded",
        current_goal="Find the sender",
        relationships="Trusts Alice",
        recent_activity="Found a letter",
        confidence=1,
        source_type=SourceType.HUMAN,
        review_status=ReviewStatus.APPROVED,
    )
    knowledge = memory.create_knowledge_item(
        "隐秘血统",
        "Eric 知道 Alice 的真实血统。",
        Authority.USER_CONFIRMED,
        ReviewStatus.APPROVED,
    )
    memory.append_knowledge_event(
        knowledge.id,
        KnowledgeSubject.CHARACTER,
        eric.id,
        first.id,
        KnowledgeState.KNOWN,
        "旧版人物知识记录",
        SourceType.HUMAN,
        ReviewStatus.APPROVED,
    )

    blocks = GenerationMemoryContextProvider(project).blocks(
        current.id,
        "Eric visits Alice.",
        (),
    )
    combined = "\n".join(block.content for block in blocks)

    assert any(block.source_type == "CHARACTER_STATE" for block in blocks)
    assert all(block.source_type != "KNOWLEDGE_EVENT" for block in blocks)
    assert "真实血统" not in combined


def test_plot_and_prose_share_one_time_bounded_reader_summary(tmp_path: Path) -> None:
    project = ProjectRepository.create(tmp_path / "novel", "Novel")
    volume = project.list_volumes()[0]
    chapters = ChapterRepository(project)
    first = chapters.create_chapter(volume.id, "Opening", "1", "Opening body")
    current = chapters.create_chapter(volume.id, "Visit", "2", "Current body")
    memory = CharacterMemoryRepository(project)
    item = memory.create_knowledge_item(
        "匿名来信",
        "读者看见信件由钟楼守夜人投递。",
        Authority.USER_CONFIRMED,
        ReviewStatus.APPROVED,
    )
    memory.append_knowledge_event(
        item.id,
        KnowledgeSubject.READER,
        project.project.id,
        first.id,
        KnowledgeState.KNOWN,
        "第一章正文",
        SourceType.HUMAN,
        ReviewStatus.APPROVED,
    )

    shared = ReaderKnowledgeSummaryService(project).summary_before(current.id)
    plot = PlotMemoryContextService(project).select(current.id, token_budget=6_000)
    prose_blocks = GenerationMemoryContextProvider(project).blocks(
        current.id,
        "Continue the story.",
        (),
    )

    assert shared is not None
    assert plot.message is not None
    assert plot.message.content.count(shared.content) == 1
    assert [
        block.content for block in prose_blocks if block.source_type == "READER_SUMMARY"
    ] == [shared.content]


def test_reviewed_reader_view_replaces_only_its_linked_legacy_reader_event(
    tmp_path: Path,
) -> None:
    project = ProjectRepository.create(tmp_path / "novel", "Novel")
    volume = project.list_volumes()[0]
    chapters = ChapterRepository(project)
    first = chapters.create_chapter(volume.id, "Opening", "1", "Opening body")
    current = chapters.create_chapter(volume.id, "Visit", "2", "Current body")
    memory = CharacterMemoryRepository(project)
    subject = memory.create_character("Eric")

    linked_item = memory.create_knowledge_item(
        "匿名来信",
        "读者看见信件由钟楼守夜人投递。",
        Authority.USER_CONFIRMED,
        ReviewStatus.APPROVED,
    )
    linked_event = memory.append_knowledge_event(
        linked_item.id,
        KnowledgeSubject.READER,
        project.project.id,
        first.id,
        KnowledgeState.KNOWN,
        "第一章正文",
        SourceType.HUMAN,
        ReviewStatus.APPROVED,
    )
    remaining_item = memory.create_knowledge_item(
        "旧港封锁",
        "读者已经知道旧港在午夜封锁。",
        Authority.USER_CONFIRMED,
        ReviewStatus.APPROVED,
    )
    remaining_event = memory.append_knowledge_event(
        remaining_item.id,
        KnowledgeSubject.READER,
        project.project.id,
        first.id,
        KnowledgeState.KNOWN,
        "第一章正文",
        SourceType.HUMAN,
        ReviewStatus.APPROVED,
    )
    ViewAssertionService(project).create_model_candidate(
        ViewAssertionDraft(
            subject_id=subject.id,
            view_type=ViewType.READER_VIEW,
            content="尚未审查的候选不能接管旧读者知识。",
            narrative_visible_from_sequence=2,
        ),
        source_id=remaining_event.id,
        source_revision=0,
    )
    assertion = ViewAssertionService(project).create_user_reader_view_from_legacy_event(
        ViewAssertionDraft(
            subject_id=subject.id,
            view_type=ViewType.READER_VIEW,
            content="读者看见信件由钟楼守夜人投递。",
            narrative_visible_from_sequence=2,
        ),
        legacy_event_id=linked_event.id,
        confirmed_by_user=True,
    )

    blocks = GenerationMemoryContextProvider(project).blocks(
        current.id,
        "Continue the story.",
        (),
    )

    reader_view = next(
        block
        for block in blocks
        if block.source_id == assertion.id
        and block.source_type == "VIEW_ASSERTION/READER_VIEW"
    )
    legacy_summary = next(
        block for block in blocks if block.source_type == "READER_SUMMARY"
    )
    assert "钟楼守夜人投递" in reader_view.content
    assert "钟楼守夜人投递" not in legacy_summary.content
    assert "旧港在午夜封锁" in legacy_summary.content


def test_plot_and_prose_share_four_time_bounded_canon_cards(tmp_path: Path) -> None:
    project = ProjectRepository.create(tmp_path / "novel", "Novel")
    volume = project.list_volumes()[0]
    chapters = ChapterRepository(project)
    first = chapters.create_chapter(volume.id, "Opening", "1", "Opening body")
    current = chapters.create_chapter(volume.id, "Visit", "2", "Current draft")
    canon = NarrativeMemoryRepository(project)
    for title, detail in (
        ("北境地理", "北境终年积雪。"),
        ("人物身份：Eric", "Eric 是温德米尔家族继承人。"),
        ("重要物品：封印地图", "地图会在月光下显现道路。"),
        ("组织：守夜人", "守夜人负责看守旧港。"),
    ):
        canon.add_canon(
            title,
            detail,
            first.id,
            confidence=1,
            authority=Authority.USER_CONFIRMED,
            review_status=ReviewStatus.APPROVED,
        )
    review = canon.add_canon(
        "待确认规则",
        "这条待审查内容不能进入正典卡。",
        first.id,
        confidence=0.5,
        authority=Authority.MODEL_EXTRACTED,
        review_status=ReviewStatus.REVIEW,
    )
    current_review = canon.add_canon(
        "当前章待审规则",
        "CURRENT_CHAPTER_REVIEW_CANON_SECRET",
        current.id,
        confidence=0.5,
        authority=Authority.MODEL_EXTRACTED,
        review_status=ReviewStatus.REVIEW,
    )
    canon.add_canon(
        "当前章秘密",
        "这条当前章内容不能提前泄漏。",
        current.id,
        confidence=1,
        authority=Authority.USER_CONFIRMED,
        review_status=ReviewStatus.APPROVED,
    )

    cards = tuple(
        card
        for card in CanonCardContextService(project).cards_before(current.id)
        if card.content
    )
    plot = PlotMemoryContextService(project).select(current.id, token_budget=6_000)
    prose_blocks = GenerationMemoryContextProvider(project).blocks(
        current.id,
        "Continue the story.",
        (),
    )

    assert [card.title for card in cards] == [
        "世界观",
        "人物身份背景",
        "重要物品、能力与兵器",
        "组织、团队与成员",
    ]
    assert plot.message is not None
    assert all(plot.message.content.count(card.content) == 1 for card in cards)
    assert [
        block.content for block in prose_blocks if block.source_type == "CANON_CARD"
    ] == [card.content for card in cards]
    candidate = next(
        block
        for block in prose_blocks
        if block.source_type == "CANON" and block.source_id == review.id
    )
    assert candidate.content == "未通过审查的正典候选"
    assert candidate.rationale == "未通过审查的正典候选"
    assert candidate.source_chapter_id == first.id
    assert candidate.source_revision is None
    assert candidate.source_hash == hashlib.sha256(
        "待确认规则\0这条待审查内容不能进入正典卡。".encode()
    ).hexdigest()
    assert candidate.eligibility.authority_allowed is False
    assert review.title not in candidate.content
    assert review.detail not in candidate.content
    assert all(block.source_id != current_review.id for block in prose_blocks)
    built = ContextBuilder().build(
        ContextBuildRequest(
            chapter_id=current.id,
            run_id="canon-review-filter",
            budget=TokenBudget(20_000, 2_000, 0),
            blocks=prose_blocks,
            deduplicate=True,
        )
    )
    omission = next(
        item
        for item in built.manifest.omitted
        if item.source_type == "CANON" and item.source_id == review.id
    )
    assert omission.reason == "HARD_FILTER:AUTHORITY_REJECTED"
    assert omission.source_revision is None
    assert not hasattr(omission, "title")
    assert not hasattr(omission, "detail")
    assert review.title not in built.text
    assert review.detail not in built.text
    assert current_review.detail not in built.text
    combined = "\n".join(card.content for card in cards)
    assert "北境终年积雪" in combined
    assert "温德米尔家族继承人" in combined
    assert "月光下显现道路" in combined
    assert "负责看守旧港" in combined
    assert "待审查内容" not in combined
    assert "当前章内容" not in combined


def test_canon_card_reports_equal_authority_conflicts_instead_of_guessing(
    tmp_path: Path,
) -> None:
    project = ProjectRepository.create(tmp_path / "novel", "Novel")
    volume = project.list_volumes()[0]
    chapters = ChapterRepository(project)
    first = chapters.create_chapter(volume.id, "Opening", "1", "Opening body")
    current = chapters.create_chapter(volume.id, "Visit", "2", "Current draft")
    canon = NarrativeMemoryRepository(project)
    for detail in ("钟楼已经封闭。", "钟楼仍然开放。"):
        canon.add_canon(
            "钟楼状态",
            detail,
            first.id,
            confidence=1,
            authority=Authority.USER_CONFIRMED,
            review_status=ReviewStatus.APPROVED,
        )
    canon.add_canon(
        "北境天气",
        "北境终年积雪。",
        first.id,
        confidence=1,
        authority=Authority.USER_CONFIRMED,
        review_status=ReviewStatus.APPROVED,
    )

    world_card = CanonCardContextService(project).cards_before(current.id)[0]

    assert [fact.title for fact in world_card.facts] == ["北境天气"]
    assert len(world_card.conflicts) == 1
    assert "冲突待处理，不得作为确定正典" in world_card.content
    assert "钟楼已经封闭" in world_card.content
    assert "钟楼仍然开放" in world_card.content

    blocks = GenerationMemoryContextProvider(project).blocks(
        current.id,
        "描写钟楼附近的行动。",
        (),
    )
    built = ContextBuilder().build(
        ContextBuildRequest(
            chapter_id=current.id,
            run_id="canon-conflict-filter",
            budget=TokenBudget(20_000, 2_000, 0),
            blocks=blocks,
            deduplicate=True,
        )
    )

    assert any(item.source_type == "CANON_CARD" for item in built.manifest.selected)
    conflict = next(
        item
        for item in built.manifest.omitted
        if item.source_type == "CANON_CONFLICT"
    )
    assert conflict.reason == "HARD_FILTER:CONFLICTED"
    assert "北境终年积雪" in built.text
    assert "钟楼已经封闭" not in built.text
    assert "钟楼仍然开放" not in built.text


def test_manual_canon_category_overrides_title_heuristic(tmp_path: Path) -> None:
    project = ProjectRepository.create(tmp_path / "novel", "Novel")
    volume = project.list_volumes()[0]
    chapters = ChapterRepository(project)
    first = chapters.create_chapter(volume.id, "Opening", "1", "Opening body")
    current = chapters.create_chapter(volume.id, "Visit", "2", "Current draft")
    NarrativeMemoryRepository(project).add_canon(
        "人物身份：月辉印记",
        "月辉印记其实是一件王室信物。",
        first.id,
        confidence=1,
        authority=Authority.USER_CONFIRMED,
        review_status=ReviewStatus.APPROVED,
        category=CanonCardCategory.ITEM_ABILITY,
    )

    cards = CanonCardContextService(project).cards_before(current.id)

    assert "月辉印记其实是一件王室信物" not in cards[1].content
    assert "月辉印记其实是一件王室信物" in cards[2].content


def test_review_clue_events_are_manifested_but_never_reach_writer_prompt(
    tmp_path: Path,
) -> None:
    project = ProjectRepository.create(tmp_path / "novel", "Novel")
    volume = project.list_volumes()[0]
    chapters = ChapterRepository(project)
    first = chapters.create_chapter(volume.id, "Opening", "1", "Opening body")
    current = chapters.create_chapter(volume.id, "Current", "2", "Current body")
    narrative = NarrativeMemoryRepository(project)
    clue = narrative.add_clue(
        ClueType.FORESHADOW,
        "批准伏笔",
        "批准伏笔正文",
        Authority.USER_CONFIRMED,
        ReviewStatus.APPROVED,
    )
    allowed = narrative.append_clue_action(
        clue.id,
        first.id,
        ClueAction.PLANT,
        "已批准事件",
        SourceType.HUMAN,
        ReviewStatus.APPROVED,
    )
    review = narrative.append_clue_action(
        clue.id,
        first.id,
        ClueAction.RESOLVE,
        "REVIEW_CLUE_EVENT_SECRET",
        SourceType.MODEL,
        ReviewStatus.REVIEW,
    )

    provider = GenerationMemoryContextProvider(project)
    blocks = provider.blocks(current.id, "继续伏笔", ())
    candidate = next(
        block for block in blocks if block.source_type == "NARRATIVE_CLUE_EVENT"
    )
    active = NarrativeClueLedger(narrative).active_before(current.id)
    built = ContextBuilder().build(
        ContextBuildRequest(
            chapter_id=current.id,
            run_id="review-clue-event-filter",
            budget=TokenBudget(20_000, 2_000, 0),
            blocks=blocks,
            deduplicate=True,
        )
    )

    assert candidate.content == "未通过审查的伏笔事件候选"
    assert candidate.source_id == review.id
    assert candidate.source_chapter_id == first.id
    assert candidate.source_revision is None
    assert candidate.source_hash == hashlib.sha256(
        f"{review.id}\x1f{review.action.value}\x1f{review.detail}".encode()
    ).hexdigest()
    assert candidate.eligibility.authority_allowed is False
    assert active[0].events == (allowed,)
    omission = next(
        item
        for item in built.manifest.omitted
        if item.source_type == "NARRATIVE_CLUE_EVENT"
    )
    assert omission.source_id == review.id
    assert omission.reason == "HARD_FILTER:AUTHORITY_REJECTED"
    assert omission.source_revision is None
    assert review.detail not in candidate.content
    assert review.detail not in built.text


def test_review_summary_is_manifested_but_never_reaches_writer_prompt(
    tmp_path: Path,
) -> None:
    project = ProjectRepository.create(tmp_path / "novel", "Novel")
    volume = project.list_volumes()[0]
    chapters = ChapterRepository(project)
    first = chapters.create_chapter(volume.id, "First", "1", "First body")
    second = chapters.create_chapter(volume.id, "Second", "2", "Second body")
    chapters.create_chapter(volume.id, "Third", "3", "Third body")
    chapters.create_chapter(volume.id, "Fourth", "4", "Fourth body")
    chapters.create_chapter(volume.id, "Fifth", "5", "Fifth body")
    current = chapters.create_chapter(volume.id, "Current", "6", "Current body")
    summaries = SummaryRepository(project)
    review = summaries.add_candidate(
        SummaryLevel.CHAPTER,
        first.id,
        "REVIEW_SUMMARY_SECRET",
        (first.id,),
        model_profile_id="provider/writer",
    )
    approved = summaries.add_human_summary(
        SummaryLevel.CHAPTER,
        second.id,
        "APPROVED_SUMMARY_BODY",
        (second.id,),
        authority=Authority.USER_CONFIRMED,
        review_status=ReviewStatus.APPROVED,
    )
    locked = summaries.add_human_summary(
        SummaryLevel.ARC,
        "opening-arc",
        "LOCKED_SUMMARY_BODY",
        (first.id,),
        authority=Authority.USER_CONFIRMED,
        review_status=ReviewStatus.LOCKED,
    )
    provider = GenerationMemoryContextProvider(project)

    blocks = provider.blocks(current.id, "Continue the story.", ())
    selected_summaries = provider.summaries.select_summary_nodes(
        current.id,
        token_budget=12_000,
    )
    summary_blocks = tuple(block for block in blocks if block.source_type == "SUMMARY")
    review_block = next(block for block in summary_blocks if block.source_id == review.id)
    approved_block = next(
        block for block in summary_blocks if block.source_id == approved.id
    )
    locked_block = next(block for block in summary_blocks if block.source_id == locked.id)
    built = ContextBuilder().build(
        ContextBuildRequest(
            chapter_id=current.id,
            run_id="review-summary-filter",
            budget=TokenBudget(20_000, 2_000, 0),
            blocks=blocks,
            deduplicate=True,
        )
    )

    assert tuple(block.source_id for block in summary_blocks) == tuple(
        summary.id for summary in selected_summaries
    )
    assert approved_block.content == provider.summaries.render(approved)
    assert approved_block.eligibility.authority_allowed is True
    assert locked_block.content == provider.summaries.render(locked)
    assert locked_block.eligibility.authority_allowed is True
    assert review_block.content == "未通过审查的摘要候选"
    assert review_block.rationale == "未通过审查的摘要候选"
    assert review_block.source_chapter_id == first.id
    assert review_block.source_revision == review.revision
    assert review_block.source_hash == review.content_hash
    assert review_block.eligibility.authority_allowed is False
    omission = next(
        item
        for item in built.manifest.omitted
        if item.source_type == "SUMMARY" and item.source_id == review.id
    )
    assert omission.reason == "HARD_FILTER:AUTHORITY_REJECTED"
    assert omission.source_chapter_id == first.id
    assert omission.source_revision == review.revision
    assert omission.source_hash == review.content_hash
    assert approved.content in built.text
    assert locked.content in built.text
    assert review.content not in built.text


def test_basic_generation_includes_relevant_state_and_compressed_history(
    tmp_path: Path,
) -> None:
    project = ProjectRepository.create(tmp_path / "novel", "Novel")
    volume = project.list_volumes()[0]
    chapters = ChapterRepository(project)
    first = chapters.create_chapter(volume.id, "Opening", "1", "Eric found the sealed map.")
    chapters.create_chapter(volume.id, "Recent", "2", "Eric hid the map from Mara.")
    current = chapters.create_chapter(volume.id, "Visit", "3")

    requirements = ChapterRequirementRepository(project)
    initial = requirements.get_or_create(current.id)
    requirements.update(
        current.id,
        "Eric meets Mara but must not reveal the sealed map.",
        is_locked=True,
        expected_revision=initial.revision,
    )
    character_memory = CharacterMemoryRepository(project)
    eric = character_memory.create_character("Eric")
    character_memory.append_state(
        eric.id,
        first.id,
        motivation="Protect the map",
        psychology="Suspicious but composed",
        current_goal="Learn why Mara arrived",
        relationships="Does not yet trust Mara",
        recent_activity="Found and concealed the map",
        confidence=1.0,
        source_type=SourceType.HUMAN,
        review_status=ReviewStatus.APPROVED,
    )
    summary = SummaryRepository(project).add_human_summary(
        SummaryLevel.CHAPTER,
        first.id,
        "Eric found a sealed map and chose to hide it.",
        (first.id,),
        authority=Authority.USER_CONFIRMED,
        review_status=ReviewStatus.APPROVED,
    )
    summary_record = next(
        record
        for record in ProjectMemoryWorkspaceGateway(project).load_before("__all__")
        if record.id == summary.id
    )
    ChapterContextPinService(ChapterContextPinRepository(project)).pin(
        current.id, summary_record
    )

    service = GenerationContextService(
        project,
        chapters,
        requirements,
        ChapterBriefRepository(project),
        GenerationRepository(project),
        ContextManifestRepository(project),
    )
    prepared = service.prepare(
        GenerationPreparationRequest(
            chapter_id=current.id,
            mode=CreationMode.BASIC,
            brief_id=None,
            output_token_limit=8_000,
            model_capabilities=ModelCapabilities(
                context_window=128_000,
                max_output_tokens=16_000,
            ),
            target_words=3_500,
            model_provider_id="provider",
            model_id="writer",
        )
    )

    selected_types = {item.source_type for item in prepared.manifest.selected}
    assert "CHARACTER_STATE" in selected_types
    assert "SUMMARY" not in selected_types
    assert "MANUAL_PIN/SUMMARY" in selected_types
    manual_block = next(
        block
        for block in service.memory_context.blocks(
            current.id,
            "Eric meets Mara but must not reveal the sealed map.",
            (),
        )
        if block.source_type == "MANUAL_PIN/SUMMARY"
    )
    assert manual_block.required is True
    assert "Protect the map" in prepared.messages[5].content
    assert prepared.messages[6].content.count("Eric found a sealed map") == 1
    assert "人工固定记忆" in prepared.messages[6].content


def test_manually_pinned_summaries_are_deduplicated_and_ordered_by_chapter(
    tmp_path: Path,
) -> None:
    project = ProjectRepository.create(tmp_path / "novel", "Novel")
    volume = project.list_volumes()[0]
    chapters = ChapterRepository(project)
    first = chapters.create_chapter(volume.id, "First", "1", "First body")
    second = chapters.create_chapter(volume.id, "Second", "2", "Second body")
    current = chapters.create_chapter(volume.id, "Current", "3")
    requirements = ChapterRequirementRepository(project)
    initial = requirements.get_or_create(current.id)
    requirements.update(
        current.id,
        "Continue the story.",
        is_locked=True,
        expected_revision=initial.revision,
    )
    summaries = SummaryRepository(project)
    first_summary = summaries.add_human_summary(
        SummaryLevel.CHAPTER,
        first.id,
        "First summary marker.",
        (first.id,),
        authority=Authority.USER_CONFIRMED,
        review_status=ReviewStatus.APPROVED,
    )
    second_summary = summaries.add_human_summary(
        SummaryLevel.CHAPTER,
        second.id,
        "Second summary marker.",
        (second.id,),
        authority=Authority.USER_CONFIRMED,
        review_status=ReviewStatus.APPROVED,
    )
    records = {
        record.id: record
        for record in ProjectMemoryWorkspaceGateway(project).load_before("__all__")
    }
    pin_service = ChapterContextPinService(ChapterContextPinRepository(project))
    pin_service.pin(current.id, records[second_summary.id])
    pin_service.pin(current.id, records[first_summary.id])
    service = GenerationContextService(
        project,
        chapters,
        requirements,
        ChapterBriefRepository(project),
        GenerationRepository(project),
        ContextManifestRepository(project),
    )

    prepared = service.prepare(
        GenerationPreparationRequest(
            chapter_id=current.id,
            mode=CreationMode.BASIC,
            brief_id=None,
            output_token_limit=8_000,
            model_capabilities=ModelCapabilities(
                context_window=128_000,
                max_output_tokens=16_000,
            ),
            target_words=3_500,
            model_provider_id="provider",
            model_id="writer",
        )
    )

    history = prepared.messages[6].content
    assert history.count("First summary marker.") == 1
    assert history.count("Second summary marker.") == 1
    assert history.index("First summary marker.") < history.index("Second summary marker.")
    selected_types = [item.source_type for item in prepared.manifest.selected]
    assert selected_types.count("MANUAL_PIN/SUMMARY") == 2
    assert "SUMMARY" not in selected_types
