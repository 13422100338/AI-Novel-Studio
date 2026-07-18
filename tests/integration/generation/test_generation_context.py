from dataclasses import replace
from pathlib import Path

import pytest

from ai_novel_studio.application.generation_context_service import (
    BASIC_UNKNOWN_CONTEXT_INPUT_LIMIT,
    GenerationContextService,
    GenerationPreparationRequest,
    StandardModeBriefError,
    UnknownContextWindowError,
)
from ai_novel_studio.application.project_guidance_service import ProjectGuidanceService
from ai_novel_studio.application.view_assertion_service import ViewAssertionService
from ai_novel_studio.core.brief.source_fingerprint import BriefSourceSnapshot
from ai_novel_studio.core.context.context_builder import (
    ContextBlock,
    ContextBuilder,
    RequiredContextOverflowError,
)
from ai_novel_studio.core.context.context_manifest import ContextManifestRepository
from ai_novel_studio.core.context.token_budget import ModelOutputLimitError
from ai_novel_studio.domain.generation import BriefStatus, CreationMode, GenerationStatus
from ai_novel_studio.domain.view import (
    EpistemicStatus,
    ViewAssertionDraft,
    ViewType,
)
from ai_novel_studio.infrastructure.llm import ModelCapabilities
from ai_novel_studio.infrastructure.storage.chapter_brief_repository import (
    BriefDraftData,
    ChapterBriefRepository,
)
from ai_novel_studio.infrastructure.storage.chapter_repository import ChapterRepository
from ai_novel_studio.infrastructure.storage.chapter_requirement_repository import (
    ChapterRequirementRepository,
)
from ai_novel_studio.infrastructure.storage.character_memory_repository import (
    CharacterMemoryRepository,
)
from ai_novel_studio.infrastructure.storage.generation_repository import GenerationRepository
from ai_novel_studio.infrastructure.storage.project_guidance_repository import (
    ProjectGuidanceRepository,
)
from ai_novel_studio.infrastructure.storage.project_repository import ProjectRepository


def _workspace(tmp_path: Path):  # type: ignore[no-untyped-def]
    project = ProjectRepository.create(tmp_path / "project", "生成上下文测试")
    volume = project.list_volumes()[0]
    chapters = ChapterRepository(project)
    old = chapters.create_chapter(volume.id, "较早章", "1", "较早正文" * 400)
    recent = chapters.create_chapter(volume.id, "上一章", "2", "近期正文" * 400)
    current = chapters.create_chapter(volume.id, "当前章", "3")
    requirements = ChapterRequirementRepository(project)
    empty = requirements.get_or_create(current.id)
    requirement = requirements.update(
        current.id,
        "主角必须在雨夜认出旧暗号，但不能揭晓寄信人。",
        is_locked=True,
        expected_revision=empty.revision,
    )
    briefs = ChapterBriefRepository(project)
    source = BriefSourceSnapshot(
        "CHAPTER_REQUIREMENT",
        requirement.id,
        requirement.revision,
        requirement.content_hash,
        True,
    )
    draft = briefs.create_draft(
        BriefDraftData(
            chapter_id=current.id,
            mode=CreationMode.STANDARD,
            dramatic_purpose="迫使主角确认危险正在逼近",
            target_length=5000,
            story_date="雨夜",
            pov_character_id=None,
            hard_events=("认出旧暗号",),
            soft_goals=("保持克制",),
            prohibited_changes=("不得揭晓寄信人",),
            creative_freedom=("自行安排暗号出现位置",),
            participants=(),
            knowledge=("主角不知道寄信人身份",),
            clue_actions=("强化旧暗号",),
            style_rules=("近距离第三人称",),
            warnings=(),
        ),
        (source,),
    )
    frozen = briefs.freeze(draft.id, expected_revision=draft.revision)
    manifests = ContextManifestRepository(project)
    runs = GenerationRepository(project)
    service = GenerationContextService(
        project,
        chapters,
        requirements,
        briefs,
        runs,
        manifests,
    )
    return {
        "project": project,
        "chapters": chapters,
        "old": old,
        "recent": recent,
        "current": current,
        "requirement": requirement,
        "briefs": briefs,
        "brief": frozen,
        "runs": runs,
        "manifests": manifests,
        "service": service,
    }


def _request(workspace, **changes):  # type: ignore[no-untyped-def]
    request = GenerationPreparationRequest(
        chapter_id=workspace["current"].id,
        mode=CreationMode.BASIC,
        brief_id=None,
        output_token_limit=32_000,
        model_capabilities=ModelCapabilities(
            context_window=128_000,
            max_output_tokens=64_000,
        ),
        target_words=5000,
        model_provider_id="provider-1",
        model_id="writer-1",
    )
    return replace(request, **changes)


def test_basic_preparation_preserves_output_limit_and_links_manifest(
    tmp_path: Path,
) -> None:
    workspace = _workspace(tmp_path)

    prepared = workspace["service"].prepare(_request(workspace))

    assert prepared.run.status == GenerationStatus.READY
    assert prepared.run.output_token_limit == 32_000
    assert prepared.run.context_manifest_id == prepared.manifest.id
    assert prepared.manifest.run_id == prepared.run.id
    assert workspace["manifests"].load(prepared.manifest.id) == prepared.manifest


def test_standard_preparation_compiles_reviewed_pov_and_reader_assertions_with_hard_filters(
    tmp_path: Path,
) -> None:
    workspace = _workspace(tmp_path)
    characters = CharacterMemoryRepository(workspace["project"])
    pov = characters.create_character("克莉丝汀")
    subject = characters.create_character("艾瑞克")
    other_viewer = characters.create_character("局外人")
    views = ViewAssertionService(workspace["project"])

    changed = views.create_user_assertion(
        ViewAssertionDraft(
            subject_id=subject.id,
            view_type=ViewType.CHARACTER_VIEW,
            viewer_subject_id=pov.id,
            epistemic_status=EpistemicStatus.KNOWS,
            content="来源改变后不应继续使用。",
        ),
        source_id=workspace["current"].id,
        source_revision=workspace["current"].revision,
        confirmed_by_user=True,
    )
    stale = views.create_model_candidate(
        ViewAssertionDraft(
            subject_id=subject.id,
            view_type=ViewType.CHARACTER_VIEW,
            viewer_subject_id=pov.id,
            epistemic_status=EpistemicStatus.SUSPECTS,
            content="旧模型候选不应继续使用。",
        ),
        source_id=workspace["current"].id,
        source_revision=workspace["current"].revision,
    )
    workspace["chapters"].save_content(
        workspace["current"].id,
        "当前章修订正文",
        source="test",
        reason="验证视角断言来源修订过滤",
        expected_revision=workspace["current"].revision,
    )

    visible_candidate = views.create_model_candidate(
        ViewAssertionDraft(
            subject_id=subject.id,
            view_type=ViewType.CHARACTER_VIEW,
            viewer_subject_id=pov.id,
            epistemic_status=EpistemicStatus.BELIEVES,
            content="克莉丝汀相信旧暗号与艾瑞克有关。",
            valid_from_sequence=3,
        ),
        source_id=workspace["current"].id,
        source_revision=workspace["chapters"].get_chapter(
            workspace["current"].id
        ).revision,
    )
    visible = views.approve_candidate(
        visible_candidate.id,
        confirmed_by_user=True,
    )
    duplicate_visible = views.create_user_assertion(
        ViewAssertionDraft(
            subject_id=subject.id,
            view_type=ViewType.CHARACTER_VIEW,
            viewer_subject_id=pov.id,
            epistemic_status=EpistemicStatus.BELIEVES,
            content="克莉丝汀相信旧暗号与艾瑞克有关。",
            valid_from_sequence=3,
        ),
        source_id="duplicate-character-view",
        source_revision=0,
        confirmed_by_user=True,
    )
    pending = views.create_model_candidate(
        ViewAssertionDraft(
            subject_id=subject.id,
            view_type=ViewType.CHARACTER_VIEW,
            viewer_subject_id=pov.id,
            epistemic_status=EpistemicStatus.SUSPECTS,
            content="尚未审查的模型猜测。",
        ),
        source_id="model-extraction-current",
        source_revision=0,
    )
    revision_mismatch = views.create_user_assertion(
        ViewAssertionDraft(
            subject_id=subject.id,
            view_type=ViewType.CHARACTER_VIEW,
            viewer_subject_id=pov.id,
            epistemic_status=EpistemicStatus.KNOWS,
            content="来源修订号不匹配时必须排除。",
        ),
        source_id=workspace["current"].id,
        source_revision=0,
        confirmed_by_user=True,
    )
    future = views.create_user_assertion(
        ViewAssertionDraft(
            subject_id=subject.id,
            view_type=ViewType.CHARACTER_VIEW,
            viewer_subject_id=pov.id,
            epistemic_status=EpistemicStatus.KNOWS,
            content="第四章才知道的真相。",
            valid_from_sequence=4,
        ),
        source_id="future-character-view",
        source_revision=0,
        confirmed_by_user=True,
    )
    reader_visible = views.create_user_assertion(
        ViewAssertionDraft(
            subject_id=subject.id,
            view_type=ViewType.READER_VIEW,
            content="第三章开始允许读者知道旧信存在。",
            narrative_visible_from_sequence=3,
        ),
        source_id="reader-visible",
        source_revision=0,
        confirmed_by_user=True,
    )
    reader_future = views.create_user_assertion(
        ViewAssertionDraft(
            subject_id=subject.id,
            view_type=ViewType.READER_VIEW,
            content="第四章前不得让读者知道寄信人。",
            narrative_visible_from_sequence=4,
        ),
        source_id="reader-future",
        source_revision=0,
        confirmed_by_user=True,
    )
    wrong_viewer = views.create_user_assertion(
        ViewAssertionDraft(
            subject_id=subject.id,
            view_type=ViewType.CHARACTER_VIEW,
            viewer_subject_id=other_viewer.id,
            epistemic_status=EpistemicStatus.KNOWS,
            content="只有局外人知道。",
        ),
        source_id="wrong-viewer",
        source_revision=0,
        confirmed_by_user=True,
    )
    world_truth = views.create_user_assertion(
        ViewAssertionDraft(
            subject_id=subject.id,
            view_type=ViewType.WORLD_TRUTH,
            content="隐藏世界真相。",
        ),
        source_id="hidden-world-truth",
        source_revision=0,
        confirmed_by_user=True,
    )
    author_plan = views.create_user_assertion(
        ViewAssertionDraft(
            subject_id=subject.id,
            view_type=ViewType.AUTHOR_PLAN,
            content="作者计划第五章让艾瑞克离开。",
        ),
        source_id="future-author-plan",
        source_revision=0,
        confirmed_by_user=True,
    )

    brief_source = workspace["briefs"].list_sources(workspace["brief"].id)[0]
    pov_draft = workspace["briefs"].create_draft(
        BriefDraftData(
            chapter_id=workspace["current"].id,
            mode=CreationMode.STANDARD,
            dramatic_purpose="验证 POV 知识边界",
            target_length=5000,
            story_date="雨夜",
            pov_character_id=pov.id,
            hard_events=("认出旧暗号",),
            soft_goals=("保持克制",),
            prohibited_changes=("不得揭晓寄信人",),
            creative_freedom=("自行安排暗号出现位置",),
            participants=(pov.id, subject.id),
            knowledge=(),
            clue_actions=(),
            style_rules=(),
            warnings=(),
        ),
        (brief_source,),
    )
    pov_brief = workspace["briefs"].freeze(
        pov_draft.id,
        expected_revision=pov_draft.revision,
    )

    prepared = workspace["service"].prepare(
        _request(
            workspace,
            mode=CreationMode.STANDARD,
            brief_id=pov_brief.id,
        )
    )

    selected_ids = {item.source_id for item in prepared.manifest.selected}
    omitted = {item.source_id: item.reason for item in prepared.manifest.omitted}
    assert {visible.id, reader_visible.id} <= selected_ids
    assert "克莉丝汀相信旧暗号与艾瑞克有关。" in "\n".join(
        message.content for message in prepared.messages
    )
    selected_rationales = {
        item.source_id: item.rationale for item in prepared.manifest.selected
    }
    assert "TASK_RELEVANCE" in selected_rationales[visible.id]
    assert duplicate_visible.id not in selected_ids
    assert omitted[duplicate_visible.id] == (
        f"DEDUPLICATED:view-assertion-{visible.id}"
    )
    assert "SOURCE_CHANGED" in omitted[changed.id]
    assert "STALE" in omitted[stale.id]
    assert "AUTHORITY_REJECTED" in omitted[pending.id]
    assert "REVISION_INVALID" in omitted[revision_mismatch.id]
    assert "TIME_BOUNDARY" in omitted[future.id]
    assert "TIME_BOUNDARY" in omitted[reader_future.id]
    recalled_ids = selected_ids | set(omitted)
    assert wrong_viewer.id not in recalled_ids
    assert world_truth.id not in recalled_ids
    assert author_plan.id not in recalled_ids
    compiled_messages = "\n".join(message.content for message in prepared.messages)
    for forbidden_text in (
        "来源改变后不应继续使用。",
        "旧模型候选不应继续使用。",
        "尚未审查的模型猜测。",
        "来源修订号不匹配时必须排除。",
        "第四章才知道的真相。",
        "第四章前不得让读者知道寄信人。",
        "只有局外人知道。",
        "隐藏世界真相。",
        "作者计划第五章让艾瑞克离开。",
    ):
        assert forbidden_text not in compiled_messages

    current = workspace["chapters"].get_chapter(workspace["current"].id)
    workspace["chapters"].save_content(
        current.id,
        "生成后再次修改当前章",
        source="test",
        reason="验证上下文清单来源依赖失效",
        expected_revision=current.revision,
    )
    with pytest.raises(KeyError, match="unknown context manifest"):
        workspace["manifests"].load(prepared.manifest.id)


def test_basic_mode_uses_conservative_input_budget_when_context_window_is_unknown(
    tmp_path: Path,
) -> None:
    workspace = _workspace(tmp_path)
    unknown_capabilities = ModelCapabilities(max_output_tokens=None)

    prepared = workspace["service"].prepare(
        _request(
            workspace,
            output_token_limit=8_000,
            model_capabilities=unknown_capabilities,
        )
    )

    assert prepared.run.status == GenerationStatus.READY
    assert prepared.run.output_token_limit == 8_000
    assert prepared.manifest.input_token_limit == BASIC_UNKNOWN_CONTEXT_INPUT_LIMIT
    assert prepared.manifest.warnings == (
        "模型未报告上下文窗口；快速模式仅使用保守的 "
        f"{BASIC_UNKNOWN_CONTEXT_INPUT_LIMIT} Token 输入预算",
    )

    with pytest.raises(UnknownContextWindowError, match="上下文窗口未知"):
        workspace["service"].prepare(
            _request(
                workspace,
                mode=CreationMode.STANDARD,
                brief_id=workspace["brief"].id,
                output_token_limit=8_000,
                model_capabilities=unknown_capabilities,
            )
        )


def test_standard_and_strict_require_current_frozen_brief(
    tmp_path: Path,
) -> None:
    workspace = _workspace(tmp_path)

    with pytest.raises(StandardModeBriefError, match="冻结 Brief"):
        workspace["service"].prepare(
            _request(workspace, mode=CreationMode.STANDARD, brief_id=None)
        )
    with pytest.raises(StandardModeBriefError, match="冻结 Brief"):
        workspace["service"].prepare(_request(workspace, mode=CreationMode.STRICT))
    strict = workspace["service"].prepare(
        _request(
            workspace,
            mode=CreationMode.STRICT,
            brief_id=workspace["brief"].id,
        )
    )
    assert strict.run.status == GenerationStatus.READY
    assert strict.run.mode == CreationMode.STRICT

    workspace["briefs"].mark_stale_for_source(
        "CHAPTER_REQUIREMENT",
        workspace["requirement"].id,
        workspace["requirement"].revision + 1,
        "changed",
    )
    assert workspace["briefs"].get(workspace["brief"].id).status == BriefStatus.STALE
    with pytest.raises(StandardModeBriefError, match="过期"):
        workspace["service"].prepare(
            _request(
                workspace,
                mode=CreationMode.STANDARD,
                brief_id=workspace["brief"].id,
            )
        )


def test_model_limit_and_required_context_overflow_fail_before_ready(
    tmp_path: Path,
) -> None:
    workspace = _workspace(tmp_path)

    with pytest.raises(ModelOutputLimitError, match="超过模型上限"):
        workspace["service"].prepare(
            _request(
                workspace,
                model_capabilities=ModelCapabilities(
                    context_window=128_000,
                    max_output_tokens=8_000,
                ),
            )
        )
    with pytest.raises(RequiredContextOverflowError, match="必需上下文块"):
        workspace["service"].prepare(
            _request(
                workspace,
                output_token_limit=80,
                model_capabilities=ModelCapabilities(
                    context_window=120,
                    max_output_tokens=100,
                ),
                safety_margin=1,
            )
        )


def test_recent_full_chapter_is_selected_before_older_full_chapter(
    tmp_path: Path,
) -> None:
    workspace = _workspace(tmp_path)

    prepared = workspace["service"].prepare(
        _request(
                workspace,
                output_token_limit=200,
                model_capabilities=ModelCapabilities(
                    context_window=1_800,
                    max_output_tokens=500,
                ),
            safety_margin=50,
        )
    )

    selected_ids = [item.source_id for item in prepared.manifest.selected]
    assert workspace["recent"].id in selected_ids
    assert selected_ids.index(workspace["recent"].id) < len(selected_ids)
    assert workspace["old"].id not in selected_ids


def test_prose_generation_guarantees_recent_continuity_before_matching_memory(
    tmp_path: Path,
) -> None:
    class CharacterEstimator:
        def estimate(self, text: str) -> int:
            return len(text)

    class MatchingMemoryContext:
        def blocks(self, *_args, **_kwargs):  # type: ignore[no-untyped-def]
            return (
                ContextBlock(
                    id="matching-memory",
                    category="MEMORY",
                    content="旧暗号" * 300,
                    priority=1,
                    required=False,
                    source_type="CANON_CARD",
                    source_id="matching-memory",
                    source_chapter_id=None,
                    source_revision=1,
                    source_hash="matching-memory-hash",
                    rationale="与任务词直接匹配的长记忆",
                ),
            )

    workspace = _workspace(tmp_path)
    workspace["service"].builder = ContextBuilder(CharacterEstimator())
    workspace["service"].memory_context = MatchingMemoryContext()

    prepared = workspace["service"].prepare(
        _request(
            workspace,
            output_token_limit=200,
            model_capabilities=ModelCapabilities(
                context_window=2_050,
                max_output_tokens=500,
            ),
            safety_margin=50,
        )
    )

    selected_ids = {item.block_id for item in prepared.manifest.selected}
    assert f"recent-{workspace['recent'].id}" in selected_ids
    assert "matching-memory" not in selected_ids


def test_with_enough_budget_exactly_the_latest_three_full_chapters_are_candidates(
    tmp_path: Path,
) -> None:
    project = ProjectRepository.create(tmp_path / "recent-three", "Novel")
    volume = project.list_volumes()[0]
    chapters = ChapterRepository(project)
    previous = [
        chapters.create_chapter(volume.id, f"Chapter {index}", str(index), f"Body {index}")
        for index in range(1, 5)
    ]
    current = chapters.create_chapter(volume.id, "Current", "5")
    requirements = ChapterRequirementRepository(project)
    empty = requirements.get_or_create(current.id)
    requirements.update(
        current.id,
        "Continue from the previous chapter.",
        is_locked=True,
        expected_revision=empty.revision,
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

    recent_blocks = tuple(
        block for block in prepared.selected_blocks if block.category == "RECENT_FULL"
    )
    assert [block.source_id for block in recent_blocks] == [
        previous[3].id,
        previous[2].id,
        previous[1].id,
    ]
    assert all(block.required is False for block in recent_blocks)
    assert previous[0].id not in {block.source_id for block in recent_blocks}


def test_standard_prompt_has_stable_order_and_prose_only_final_task(
    tmp_path: Path,
) -> None:
    workspace = _workspace(tmp_path)

    prepared = workspace["service"].prepare(
        _request(
            workspace,
            mode=CreationMode.STANDARD,
            brief_id=workspace["brief"].id,
        )
    )

    assert [message.role for message in prepared.messages] == [
        "system",
        "system",
        "user",
        "user",
        "user",
        "user",
        "user",
        "user",
    ]
    assert "当前章要求" in prepared.messages[2].content
    assert "冻结 Brief" in prepared.messages[3].content
    assert "近期章节全文" in prepared.messages[4].content
    assert "人物、知识、线索、正典和文风" in prepared.messages[5].content
    assert "历史摘要与检索证据" in prepared.messages[6].content
    assert prepared.messages[-1].content.endswith("只输出本章正文。")


def test_project_guidance_is_required_system_context_and_manifest_records_revision(
    tmp_path: Path,
) -> None:
    workspace = _workspace(tmp_path)
    guidance = ProjectGuidanceService(
        ProjectGuidanceRepository(workspace["project"])
    ).save_manual(
        "主题是人在失去记忆后仍然选择承担责任。\n使用近距离第三人称。",
        expected_revision=0,
    )

    prepared = workspace["service"].prepare(_request(workspace))

    selected = next(
        item
        for item in prepared.manifest.selected
        if item.source_type == "PROJECT_GUIDANCE"
    )
    assert selected.category == "PROJECT_GUIDANCE"
    assert selected.source_id == workspace["project"].project.id
    assert selected.source_revision == guidance.revision
    assert not any(
        item.source_type == "PROJECT_GUIDANCE" for item in prepared.manifest.omitted
    )
    assert prepared.messages[2].role == "system"
    assert "小说最高系统提示" in prepared.messages[2].content
    assert guidance.highest_system_prompt in prepared.messages[2].content
