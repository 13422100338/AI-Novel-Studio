from pathlib import Path

from ai_novel_studio.application.character_identity_service import (
    CharacterIdentityService,
)
from ai_novel_studio.domain.memory import ReviewStatus, SourceType
from ai_novel_studio.infrastructure.storage.chapter_repository import ChapterRepository
from ai_novel_studio.infrastructure.storage.character_memory_repository import (
    CharacterMemoryRepository,
)
from ai_novel_studio.infrastructure.storage.project_repository import ProjectRepository


def _project_with_chapter(tmp_path: Path):  # type: ignore[no-untyped-def]
    project = ProjectRepository.create(tmp_path / "project", "人物冲突候选测试")
    volume = project.list_volumes()[0]
    chapter = ChapterRepository(project).create_chapter(volume.id, "电报抵达", "1")
    return project, chapter


def test_review_candidates_match_full_name_and_short_name_with_evidence(
    tmp_path: Path,
) -> None:
    project, chapter = _project_with_chapter(tmp_path)
    memory = CharacterMemoryRepository(project)
    short_card = memory.create_character("艾瑞克", profile="简称人物卡")
    full_card = memory.create_character(
        "艾瑞克·温德米尔", aliases=("温德米尔",), profile="正式人物卡"
    )
    memory.create_character("克莉丝汀")
    memory.append_state(
        short_card.id,
        chapter.id,
        motivation="证明自己",
        psychology="克制",
        current_goal="完成述职",
        relationships="信任克莉丝汀",
        recent_activity="收到公爵府电报",
        confidence=0.9,
        source_type=SourceType.MODEL,
        review_status=ReviewStatus.REVIEW,
    )

    candidates = CharacterIdentityService(project).list_review_candidates()

    assert len(candidates) == 1
    candidate = candidates[0]
    assert {candidate.left.character.id, candidate.right.character.id} == {
        short_card.id,
        full_card.id,
    }
    assert candidate.recommended_character_id == full_card.id
    assert "简称" in candidate.reason
    short_snapshot = (
        candidate.left
        if candidate.left.character.id == short_card.id
        else candidate.right
    )
    assert short_snapshot.state_count == 1
    assert short_snapshot.evidence[0].chapter_title == "电报抵达"
    assert "收到公爵府电报" in short_snapshot.evidence[0].summary


def test_review_candidates_require_a_meaningful_name_relation(tmp_path: Path) -> None:
    project, _chapter = _project_with_chapter(tmp_path)
    memory = CharacterMemoryRepository(project)
    memory.create_character("王")
    memory.create_character("王国法")
    memory.create_character("克莉丝汀")
    memory.create_character("艾瑞克")

    assert CharacterIdentityService(project).list_review_candidates() == ()


def test_recent_applied_merges_are_available_for_undo(tmp_path: Path) -> None:
    project, _chapter = _project_with_chapter(tmp_path)
    memory = CharacterMemoryRepository(project)
    source = memory.create_character("艾瑞克")
    target = memory.create_character("艾瑞克·温德米尔")
    service = CharacterIdentityService(project)
    merge = service.merge(
        source.id,
        target.id,
        reason="用户确认简称与全称为同一人物",
        confirmed_by_user=True,
    )

    recent = service.list_recent_applied_merges()

    assert len(recent) == 1
    assert recent[0].merge.id == merge.id
    assert recent[0].source_name == "艾瑞克"
    assert recent[0].target_name == "艾瑞克·温德米尔"

    service.undo(merge.id, confirmed_by_user=True)

    assert service.list_recent_applied_merges() == ()
