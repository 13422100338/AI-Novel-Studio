from dataclasses import FrozenInstanceError
from datetime import UTC, datetime

import pytest

from ai_novel_studio.domain.generation import (
    BriefSource,
    BriefStatus,
    ChapterBrief,
    ChapterRequirement,
    CreationMode,
    GenerationCheckpoint,
    GenerationRun,
    GenerationStatus,
)


def _now() -> datetime:
    return datetime.now(UTC)


def test_phase_five_enums_expose_stable_storage_values() -> None:
    assert CreationMode.BASIC.value == "BASIC"
    assert CreationMode.STANDARD.value == "STANDARD"
    assert CreationMode.STRICT.value == "STRICT"
    assert BriefStatus.FROZEN.value == "FROZEN"
    assert GenerationStatus.PARTIAL.value == "PARTIAL"
    assert GenerationStatus.ACCEPTED.value == "ACCEPTED"


def test_generation_records_are_immutable_and_keep_source_provenance() -> None:
    now = _now()
    requirement = ChapterRequirement(
        "requirement-1", "chapter-1", "必须收到来信", True, 2, "requirement-hash", now, now
    )
    source = BriefSource(
        "source-1", "brief-1", "CHAPTER_REQUIREMENT", requirement.id, 2,
        requirement.content_hash, True
    )
    brief = ChapterBrief(
        id="brief-1",
        chapter_id="chapter-1",
        mode=CreationMode.STANDARD,
        status=BriefStatus.FROZEN,
        revision=1,
        dramatic_purpose="推动主角主动调查",
        target_length=3500,
        story_date="冬至前夜",
        pov_character_id="character-1",
        hard_events=("收到来信",),
        soft_goals=("保持怀疑",),
        prohibited_changes=("不得揭晓寄信人",),
        creative_freedom=("自行设计来信位置",),
        participants=("character-1",),
        knowledge=("主角只认得暗号",),
        clue_actions=("强化旧暗号",),
        style_rules=("克制的近距离第三人称",),
        warnings=(),
        source_fingerprint="source-fingerprint",
        content_hash="brief-hash",
        cloned_from_id=None,
        created_at=now,
        updated_at=now,
        frozen_at=now,
    )

    assert source.required is True
    assert brief.hard_events == ("收到来信",)
    with pytest.raises(FrozenInstanceError):
        requirement.content = "覆盖"  # type: ignore[misc]


def test_invalid_revisions_lengths_and_usage_are_rejected() -> None:
    now = _now()
    with pytest.raises(ValueError, match="revision"):
        ChapterRequirement("r", "chapter", "要求", False, -1, "hash", now, now)
    with pytest.raises(ValueError, match="target_length"):
        ChapterBrief(
            "b", "chapter", CreationMode.STANDARD, BriefStatus.DRAFT, 0, "目的", 0,
            "", None, (), (), (), (), (), (), (), (), (), "fingerprint", "hash", None,
            now, now, None
        )
    with pytest.raises(ValueError, match="Token"):
        GenerationRun(
            id="run-1",
            chapter_id="chapter-1",
            mode=CreationMode.BASIC,
            status=GenerationStatus.PREPARING,
            brief_id=None,
            brief_revision=None,
            context_manifest_id=None,
            model_provider_id="provider-1",
            model_id="model-1",
            output_token_limit=8000,
            prompt_version="prose-v1",
            accepted_chapter_revision=None,
            input_tokens=-1,
            output_tokens=None,
            cached_input_tokens=None,
            reasoning_tokens=None,
            failure_code=None,
            failure_message=None,
            started_at=now,
            updated_at=now,
            completed_at=None,
            accepted_at=None,
        )


def test_checkpoint_rejects_negative_sequence() -> None:
    with pytest.raises(ValueError, match="sequence"):
        GenerationCheckpoint(
            "checkpoint-1", "run-1", -1, ".ai_pipeline/checkpoints/one.md", "hash",
            None, _now()
        )
