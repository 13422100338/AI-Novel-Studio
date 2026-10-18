from __future__ import annotations

from pathlib import Path

import pytest

from ai_novel_studio.application.chapter_revision_service import ChapterRevisionService
from ai_novel_studio.application.subject_merge_service import (
    SubjectMergeError,
    SubjectMergePreview,
    SubjectMergeService,
)
from ai_novel_studio.domain.character_identity import CharacterMergeStatus
from ai_novel_studio.domain.identifiers import new_id
from ai_novel_studio.domain.memory import ReviewStatus, SourceType
from ai_novel_studio.infrastructure.storage.character_memory_repository import (
    CharacterMemoryRepository,
)
from ai_novel_studio.infrastructure.storage.project_repository import ProjectRepository


def _setup(tmp_path: Path):
    project = ProjectRepository.create(tmp_path / "novel", "Subject merge")
    volume = project.list_volumes()[0]
    chapter = ChapterRevisionService(project).submit_creation(
        volume.id, "Chapter", content="正文"
    ).chapter
    memory = CharacterMemoryRepository(project)
    source = memory.create_character("艾瑞克", aliases=("白鸦镇领主", "艾瑞"))
    target = memory.create_character("温德米尔", aliases=("艾瑞",))
    return SubjectMergeService(project), memory, chapter, source, target


def test_preview_reports_aliases_and_counts(tmp_path: Path) -> None:
    service, memory, chapter, source, target = _setup(tmp_path)
    memory.append_state(
        source.id,
        chapter.id,
        motivation="找旧友",
        psychology="坚定",
        current_goal="抵达旧港",
        relationships="",
        recent_activity="",
        location="旧港",
        injury_status="无",
        source_type=SourceType.MODEL,
        review_status=ReviewStatus.REVIEW,
        confidence=0.8,
    )

    preview = service.preview(source.id, target.id)

    assert isinstance(preview, SubjectMergePreview)
    assert preview.aliases_to_preserve == ("白鸦镇领主",)
    assert preview.state_event_count == 1
    assert preview.shared_chapter_conflict_count == 0
    assert preview.reversible is True


def test_preview_counts_shared_chapter_conflicts(tmp_path: Path) -> None:
    service, memory, chapter, source, target = _setup(tmp_path)
    for character in (source, target):
        memory.append_state(
            character.id,
            chapter.id,
            motivation="动机",
            psychology="心理",
            current_goal="目标",
            relationships="",
            recent_activity="",
            location="地点",
            injury_status="无",
            source_type=SourceType.MODEL,
            review_status=ReviewStatus.REVIEW,
            confidence=0.8,
        )

    preview = service.preview(source.id, target.id)

    assert preview.shared_chapter_conflict_count == 1


def test_preview_rejects_unknown_or_same_character(tmp_path: Path) -> None:
    service, _memory, _chapter, source, _target = _setup(tmp_path)

    with pytest.raises(SubjectMergeError):
        service.preview(str(new_id()), source.id)
    with pytest.raises(SubjectMergeError):
        service.preview(source.id, source.id)


def test_merge_requires_user_confirmation_and_can_undo(tmp_path: Path) -> None:
    service, _memory, _chapter, source, target = _setup(tmp_path)

    with pytest.raises(SubjectMergeError):
        service.merge(
            source.id, target.id, reason="同一人", confirmed_by_user=False
        )

    merge = service.merge(
        source.id, target.id, reason="同一人", confirmed_by_user=True
    )
    assert merge.status is CharacterMergeStatus.APPLIED

    undone = service.undo(merge.id, confirmed_by_user=True)
    assert undone.status is CharacterMergeStatus.REVERSED


def test_merge_revalidates_expected_state_count_inside_commit(
    tmp_path: Path,
) -> None:
    service, memory, chapter, source, target = _setup(tmp_path)
    expected = (("subject.state_events:" + source.id, 0),)
    memory.append_state(
        source.id,
        chapter.id,
        motivation="发生在预览之后",
        psychology="警觉",
        current_goal="阻止过期归并",
        relationships="",
        recent_activity="",
        location="旧港",
        injury_status="无",
        source_type=SourceType.MODEL,
        review_status=ReviewStatus.REVIEW,
        confidence=0.8,
    )

    with pytest.raises(SubjectMergeError, match="changed since proposal"):
        service.merge(
            source.id,
            target.id,
            reason="同一人",
            confirmed_by_user=True,
            expected_revisions=expected,
        )

    assert memory.get_character(source.id).id == source.id
    assert memory.get_character(target.id).id == target.id
