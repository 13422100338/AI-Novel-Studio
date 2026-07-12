import hashlib
from pathlib import Path

import pytest

from ai_novel_studio.application.chapter_requirement_service import (
    ChapterRequirementService,
    LockedRequirementError,
)
from ai_novel_studio.infrastructure.storage.chapter_repository import ChapterRepository
from ai_novel_studio.infrastructure.storage.chapter_requirement_repository import (
    ChapterRequirementRepository,
    StaleRequirementError,
)
from ai_novel_studio.infrastructure.storage.project_repository import ProjectRepository


def _service_with_two_chapters(
    tmp_path: Path,
) -> tuple[ChapterRequirementService, tuple[str, str]]:
    project = ProjectRepository.create(tmp_path / "project", "要求测试")
    volume = project.list_volumes()[0]
    chapters = ChapterRepository(project)
    first = chapters.create_chapter(volume.id, "同名章节", "1")
    second = chapters.create_chapter(volume.id, "同名章节", "2")
    repository = ChapterRequirementRepository(project)
    return ChapterRequirementService(repository), (first.id, second.id)


def test_get_or_create_stores_one_empty_requirement_per_chapter(tmp_path: Path) -> None:
    service, chapter_ids = _service_with_two_chapters(tmp_path)

    first = service.get_or_create(chapter_ids[0])
    same = service.get_or_create(chapter_ids[0])

    assert first == same
    assert first.content == ""
    assert first.is_locked is False
    assert first.revision == 0
    assert first.content_hash == hashlib.sha256(b"").hexdigest()


def test_user_can_explicitly_lock_edit_and_unlock_with_optimistic_revision(
    tmp_path: Path,
) -> None:
    service, chapter_ids = _service_with_two_chapters(tmp_path)
    created = service.get_or_create(chapter_ids[0])

    locked = service.save_user(
        chapter_ids[0], "  必须收到来信  ", is_locked=True, expected_revision=created.revision
    )
    unlocked = service.save_user(
        chapter_ids[0], "改为发现旧暗号", is_locked=False, expected_revision=locked.revision
    )

    assert locked.content == "必须收到来信"
    assert locked.is_locked is True
    assert locked.revision == 1
    assert unlocked.is_locked is False
    assert unlocked.revision == 2


def test_model_candidate_cannot_override_lock_or_stale_revision(tmp_path: Path) -> None:
    service, chapter_ids = _service_with_two_chapters(tmp_path)
    created = service.get_or_create(chapter_ids[0])
    locked = service.save_user(
        chapter_ids[0], "人工锁定要求", is_locked=True, expected_revision=created.revision
    )

    with pytest.raises(LockedRequirementError, match="锁定"):
        service.apply_model_candidate(
            chapter_ids[0], "模型覆盖", expected_revision=locked.revision
        )

    unlocked = service.save_user(
        chapter_ids[0], "人工解锁要求", is_locked=False, expected_revision=locked.revision
    )
    with pytest.raises(StaleRequirementError, match="修订"):
        service.apply_model_candidate(
            chapter_ids[0], "过期模型候选", expected_revision=locked.revision
        )
    applied = service.apply_model_candidate(
        chapter_ids[0], "模型建议要求", expected_revision=unlocked.revision
    )

    assert applied.content == "模型建议要求"
    assert applied.is_locked is False
    assert service.get_or_create(chapter_ids[0]).content == "模型建议要求"


def test_empty_save_is_rejected_and_duplicate_titles_do_not_share_requirement(
    tmp_path: Path,
) -> None:
    service, chapter_ids = _service_with_two_chapters(tmp_path)
    first = service.get_or_create(chapter_ids[0])
    second = service.get_or_create(chapter_ids[1])

    with pytest.raises(ValueError, match="要求"):
        service.save_user(chapter_ids[0], "   ", is_locked=False, expected_revision=0)

    assert first.id != second.id
    assert first.chapter_id != second.chapter_id
