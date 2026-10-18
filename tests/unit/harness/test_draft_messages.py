from __future__ import annotations

from datetime import UTC, datetime

from ai_novel_studio.domain.generation import AuditPolicy, GenerationProfile
from ai_novel_studio.domain.identifiers import new_id
from ai_novel_studio.domain.project_constitution import (
    ConstitutionRule,
    ProjectConstitution,
)
from ai_novel_studio.harness.agent_loop import build_draft_messages
from ai_novel_studio.harness.constitution_flow import ConstitutionFlowService
from ai_novel_studio.harness.generation_package import EditorSnapshot, GenerationPackage


def _package(**overrides: object) -> GenerationPackage:
    chapter_id = str(new_id())
    fields: dict[str, object] = dict(
        chapter_id=chapter_id,
        editor_snapshot=EditorSnapshot(chapter_id, "旧正文", 0, "a" * 64),
        formal_revision=0,
        generation_profile=GenerationProfile.QUICK,
        audit_policy=AuditPolicy.MINIMAL,
        goal="写第三章",
        knowledge_known=("艾瑞克知道黑鸦身份",),
        knowledge_unaware=("克莉丝汀不知道黑鸦身份",),
        knowledge_unknown=("宝藏位置未知",),
        story_time="黄昏",
    )
    fields.update(overrides)
    return GenerationPackage(**fields)


def _constitution() -> ProjectConstitution:
    return ProjectConstitution(
        id=str(new_id()),
        project_id=str(new_id()),
        revision=3,
        shared_creative_rules=(ConstitutionRule("tone.default", "压抑克制"),),
        agent_only_rules=(ConstitutionRule("agent.planning", "先提问再计划"),),
        writer_only_rules=(ConstitutionRule("prose.sentence", "短句优先"),),
        overridable_rules=(ConstitutionRule("tone.default", "压抑克制"),),
        non_overridable_rules=(ConstitutionRule("canon.locked", "禁止改写已确认设定"),),
        source_decisions=("已确认",),
        unresolved_exclusions=(),
        approved_by_author=True,
        created_at=datetime.now(UTC),
    )


def test_writer_component_contains_only_writer_layers() -> None:
    component = ConstitutionFlowService.to_writer_prompt_component(_constitution())

    assert "tone.default" in component.content
    assert "prose.sentence" in component.content
    assert "agent.planning" not in component.content
    assert "canon.locked" not in component.content
    assert "可覆盖规则" not in component.content


def test_draft_messages_place_constitution_in_project_prefix_and_keep_input_last() -> None:
    package = _package()
    writer = ConstitutionFlowService.to_writer_prompt_component(_constitution())

    messages = build_draft_messages(package, "编译文本", writer)

    roles = [message.role for message in messages]
    assert roles[0] == "system"
    assert roles[-1] == "user"
    assert messages[-1].content.startswith("请创作本章正文")
    system_text = "\n".join(
        message.content for message in messages if message.role == "system"
    )
    assert "压抑克制" in system_text
    assert "先提问再计划" not in system_text


def test_draft_messages_carry_knowledge_boundaries_in_task_block() -> None:
    messages = build_draft_messages(_package(), "编译文本")

    task_block = next(
        message for message in messages if "任务目标" in message.content
    )
    assert "已知(必须遵守)" in task_block.content
    assert "不得写出其知情(角色不知晓)" in task_block.content
    assert "未知(不得擅自补全)" in task_block.content
    assert "故事时间：黄昏" in task_block.content


def test_same_revision_yields_reproducible_messages() -> None:
    package = _package()
    writer = ConstitutionFlowService.to_writer_prompt_component(_constitution())

    first = build_draft_messages(package, "编译文本", writer)
    second = build_draft_messages(package, "编译文本", writer)

    assert first == second


def test_without_constitution_no_writer_rules_leak() -> None:
    messages = build_draft_messages(_package(), "编译文本")

    combined = "\n".join(message.content for message in messages)
    assert "压抑克制" not in combined
