import hashlib
from pathlib import Path

import pytest

from ai_novel_studio.infrastructure.storage.chapter_repository import ChapterRepository
from ai_novel_studio.infrastructure.storage.project_repository import ProjectRepository
from ai_novel_studio.infrastructure.storage.view_assertion_repository import (
    ViewAssertionRepository,
)


def _repositories(tmp_path: Path) -> tuple[ProjectRepository, ChapterRepository]:
    project = ProjectRepository.create(tmp_path / "novel", "My Novel")
    return project, ChapterRepository(project)


def test_create_writes_canonical_utf8_markdown_and_preserves_order(tmp_path: Path) -> None:
    project, chapters = _repositories(tmp_path)
    volume = project.list_volumes()[0]

    first = chapters.create_chapter(volume.id, "开端", "第一章", "正文一")
    second = chapters.create_chapter(volume.id, "继续", "第二章", "正文二")

    assert chapters.read_content(first.id) == "正文一"
    assert not Path(first.content_path).is_absolute()
    assert (project.layout.root / first.content_path).read_bytes() == "正文一".encode()
    assert [chapter.id for chapter in chapters.list_chapters(volume.id)] == [first.id, second.id]


def test_save_snapshots_previous_revision_before_atomic_replace(tmp_path: Path) -> None:
    project, chapters = _repositories(tmp_path)
    chapter = chapters.create_chapter(project.list_volumes()[0].id, "Opening", "1", "old")

    updated = chapters.save_content(chapter.id, "new", source="manual", reason="rewrite")
    versions = chapters.list_versions(chapter.id)

    assert updated.revision == 1
    assert chapters.read_content(chapter.id) == "new"
    assert len(versions) == 1
    assert versions[0].revision == 0
    snapshot = project.layout.root / versions[0].content_snapshot_path
    assert snapshot.read_text(encoding="utf-8") == "old"
    assert versions[0].content_hash == hashlib.sha256(b"old").hexdigest()


def test_view_invalidation_failure_restores_chapter_file_and_database(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project, chapters = _repositories(tmp_path)
    chapter = chapters.create_chapter(
        project.list_volumes()[0].id,
        "Opening",
        "1",
        "old",
    )

    def fail_invalidation(*_args: object, **_kwargs: object) -> None:
        raise RuntimeError("injected view invalidation failure")

    monkeypatch.setattr(
        ViewAssertionRepository,
        "invalidate_source_revision_in_connection",
        fail_invalidation,
    )

    with pytest.raises(RuntimeError, match="injected view invalidation failure"):
        chapters.save_content(
            chapter.id,
            "new",
            source="manual",
            reason="rewrite",
        )

    restored = chapters.get_chapter(chapter.id)
    assert restored.revision == 0
    assert chapters.read_content(chapter.id) == "old"
    assert chapters.list_versions(chapter.id) == []
    history = project.layout.history / chapter.id
    assert not history.exists() or not tuple(history.iterdir())


def test_delete_moves_chapter_to_trash_and_restore_recovers_it(tmp_path: Path) -> None:
    project, chapters = _repositories(tmp_path)
    chapter = chapters.create_chapter(project.list_volumes()[0].id, "Opening", "1", "body")
    canonical = project.layout.root / chapter.content_path

    chapters.delete_chapter(chapter.id)

    assert not canonical.exists()
    assert chapters.list_chapters() == []
    assert any(project.layout.trash.iterdir())

    restored = chapters.restore_chapter(chapter.id)
    assert restored.is_deleted is False
    assert chapters.read_content(chapter.id) == "body"


def test_delete_volume_reassigns_chapters_and_removes_empty_volume(tmp_path: Path) -> None:
    project, chapters = _repositories(tmp_path)
    target = project.list_volumes()[0]
    source = project.create_volume("Part Two")
    chapter = chapters.create_chapter(source.id, "Opening", "1", "body")

    chapters.delete_volume(source.id, target.id)

    assert [volume.id for volume in project.list_volumes()] == [target.id]
    moved = chapters.list_chapters(target.id)[0]
    assert moved.id == chapter.id
    assert moved.volume_id == target.id
    assert chapters.read_content(moved.id) == "body"
    assert f"volume_{target.id}" in moved.content_path


def test_volume_cannot_be_deleted_into_itself(tmp_path: Path) -> None:
    project, chapters = _repositories(tmp_path)
    volume = project.list_volumes()[0]

    with pytest.raises(ValueError, match="different"):
        chapters.delete_volume(volume.id, volume.id)
