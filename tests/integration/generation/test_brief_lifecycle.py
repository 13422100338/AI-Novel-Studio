from dataclasses import replace
from pathlib import Path

import pytest

from ai_novel_studio.application.brief_lifecycle_service import (
    BriefLifecycleService,
    BriefValidationError,
)
from ai_novel_studio.core.brief.source_fingerprint import (
    BriefSourceSnapshot,
    compute_source_fingerprint,
)
from ai_novel_studio.domain.generation import BriefStatus, CreationMode
from ai_novel_studio.infrastructure.storage.chapter_brief_repository import (
    BriefDraftData,
    ChapterBriefRepository,
    ImmutableBriefError,
    StaleBriefError,
)
from ai_novel_studio.infrastructure.storage.chapter_repository import ChapterRepository
from ai_novel_studio.infrastructure.storage.project_repository import ProjectRepository


class SourceProvider:
    def __init__(self, sources: tuple[BriefSourceSnapshot, ...]) -> None:
        self.sources = sources

    def current_sources(self, _brief_id: str) -> tuple[BriefSourceSnapshot, ...]:
        return self.sources


def _source(
    source_type: str,
    source_id: str,
    revision: int,
    source_hash: str,
    *,
    required: bool = True,
) -> BriefSourceSnapshot:
    return BriefSourceSnapshot(source_type, source_id, revision, source_hash, required)


def _draft_data(chapter_id: str, purpose: str = "推动主角调查") -> BriefDraftData:
    return BriefDraftData(
        chapter_id=chapter_id,
        mode=CreationMode.STANDARD,
        dramatic_purpose=purpose,
        target_length=3500,
        story_date="冬至前夜",
        pov_character_id="character-1",
        hard_events=("收到来信",),
        soft_goals=("保持怀疑",),
        prohibited_changes=("不得揭晓寄信人",),
        creative_freedom=("自行安排来信位置",),
        participants=("character-1",),
        knowledge=("主角只认得暗号",),
        clue_actions=("强化旧暗号",),
        style_rules=("克制的近距离第三人称",),
        warnings=(),
    )


def _repository(tmp_path: Path) -> tuple[ChapterBriefRepository, str]:
    project = ProjectRepository.create(tmp_path / "project", "Brief 测试")
    volume = project.list_volumes()[0]
    chapter = ChapterRepository(project).create_chapter(volume.id, "测试章", "1")
    return ChapterBriefRepository(project), chapter.id


def test_source_fingerprint_is_deterministic_and_sensitive_to_provenance() -> None:
    requirement = _source("CHAPTER_REQUIREMENT", "requirement-1", 2, "hash-r")
    canon = _source("CANON", "canon-1", 1, "hash-c", required=False)

    first = compute_source_fingerprint((requirement, canon))
    second = compute_source_fingerprint((canon, requirement))
    changed = compute_source_fingerprint((replace(requirement, source_revision=3), canon))

    assert first == second
    assert first != changed


def test_draft_can_be_edited_but_frozen_brief_is_immutable(tmp_path: Path) -> None:
    repository, chapter_id = _repository(tmp_path)
    sources = (_source("CHAPTER_REQUIREMENT", "requirement-1", 0, "hash-r"),)
    provider = SourceProvider(sources)
    service = BriefLifecycleService(repository, provider)
    draft = repository.create_draft(_draft_data(chapter_id), sources)

    edited = repository.update_draft(
        draft.id,
        _draft_data(chapter_id, "改为迫使主角离开安全区"),
        expected_revision=0,
    )
    frozen = service.freeze(edited.id, expected_revision=edited.revision)

    assert edited.revision == 1
    assert frozen.status == BriefStatus.FROZEN
    assert frozen.frozen_at is not None
    with pytest.raises(ImmutableBriefError, match="冻结"):
        repository.update_draft(
            frozen.id, _draft_data(chapter_id, "尝试覆盖"), expected_revision=frozen.revision
        )


def test_freezing_new_brief_archives_previous_frozen_brief_atomically(
    tmp_path: Path,
) -> None:
    repository, chapter_id = _repository(tmp_path)
    sources = (_source("CHAPTER_REQUIREMENT", "requirement-1", 0, "hash-r"),)
    service = BriefLifecycleService(repository, SourceProvider(sources))
    first = repository.create_draft(_draft_data(chapter_id, "第一版"), sources)
    first = service.freeze(first.id, expected_revision=0)
    second = repository.create_draft(_draft_data(chapter_id, "第二版"), sources)

    second = service.freeze(second.id, expected_revision=0)

    assert second.status == BriefStatus.FROZEN
    assert repository.get(first.id).status == BriefStatus.ARCHIVED
    assert [brief.id for brief in repository.list_for_chapter(chapter_id, BriefStatus.FROZEN)] == [
        second.id
    ]


def test_source_change_marks_frozen_brief_stale_without_deleting_content(
    tmp_path: Path,
) -> None:
    repository, chapter_id = _repository(tmp_path)
    sources = (
        _source("CHAPTER_REQUIREMENT", "requirement-1", 0, "hash-r"),
        _source("CANON", "canon-1", 1, "hash-c", required=False),
    )
    service = BriefLifecycleService(repository, SourceProvider(sources))
    frozen = service.freeze(
        repository.create_draft(_draft_data(chapter_id), sources).id,
        expected_revision=0,
    )

    affected = service.mark_stale_for_source("CANON", "canon-1", 2, "hash-new")

    stale = repository.get(frozen.id)
    assert affected == (frozen.id,)
    assert stale.status == BriefStatus.STALE
    assert stale.dramatic_purpose == frozen.dramatic_purpose
    assert repository.list_sources(stale.id)[1].source_hash == "hash-c"


def test_clone_uses_current_sources_and_reports_added_removed_changed(
    tmp_path: Path,
) -> None:
    repository, chapter_id = _repository(tmp_path)
    original_sources = (
        _source("CHAPTER_REQUIREMENT", "requirement-1", 0, "hash-r"),
        _source("CANON", "canon-old", 1, "hash-old", required=False),
        _source("STYLE", "style-1", 1, "hash-style", required=False),
    )
    provider = SourceProvider(original_sources)
    service = BriefLifecycleService(repository, provider)
    frozen = service.freeze(
        repository.create_draft(_draft_data(chapter_id), original_sources).id,
        expected_revision=0,
    )
    service.mark_stale_for_source("STYLE", "style-1", 2, "hash-style-new")
    provider.sources = (
        original_sources[0],
        replace(original_sources[2], source_revision=2, source_hash="hash-style-new"),
        _source("CLUE", "clue-1", 0, "hash-clue", required=False),
    )

    result = service.clone_as_draft(frozen.id)

    assert result.brief.status == BriefStatus.DRAFT
    assert result.brief.cloned_from_id == frozen.id
    assert result.added == (("CLUE", "clue-1"),)
    assert result.removed == (("CANON", "canon-old"),)
    assert result.changed == (("STYLE", "style-1"),)
    assert repository.get(frozen.id).status == BriefStatus.STALE


def test_freeze_rejects_stale_revision_and_missing_required_requirement(
    tmp_path: Path,
) -> None:
    repository, chapter_id = _repository(tmp_path)
    sources = (_source("CHAPTER_REQUIREMENT", "requirement-1", 0, "hash-r"),)
    draft = repository.create_draft(_draft_data(chapter_id), sources)

    with pytest.raises(StaleBriefError, match="修订"):
        BriefLifecycleService(repository, SourceProvider(sources)).freeze(
            draft.id, expected_revision=99
        )
    with pytest.raises(BriefValidationError, match="当前章要求"):
        BriefLifecycleService(repository, SourceProvider(())).freeze(
            draft.id, expected_revision=draft.revision
        )
