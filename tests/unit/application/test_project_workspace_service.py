from pathlib import Path

import pytest

from ai_novel_studio.application.project_workspace_service import (
    ProjectWorkspaceService,
    WorkspaceNotOpenError,
)
from ai_novel_studio.infrastructure.storage.chapter_repository import ChapterRepository
from ai_novel_studio.infrastructure.storage.project_repository import ProjectRepository


def test_workspace_creates_project_and_returns_tree(tmp_path: Path) -> None:
    service = ProjectWorkspaceService()

    summary = service.create_project(tmp_path / "novel", "My Novel")
    tree = service.volume_tree()

    assert summary.title == "My Novel"
    assert summary.root == (tmp_path / "novel").resolve()
    assert len(tree) == 1
    assert tree[0].chapters == ()
    service.close_project()


def test_workspace_loads_and_saves_chapter_without_bypassing_history(
    tmp_path: Path,
) -> None:
    project = ProjectRepository.create(tmp_path / "novel", "My Novel")
    chapter_repo = ChapterRepository(project)
    chapter = chapter_repo.create_chapter(
        project.list_volumes()[0].id,
        "Opening",
        "1",
        "old text",
    )
    service = ProjectWorkspaceService()
    service.open_project(project.layout.root)

    workspace = service.load_chapter(chapter.id)
    saved = service.save_chapter(
        chapter.id,
        "new text",
        expected_revision=workspace.revision,
        requirement_content="must happen",
        expected_requirement_revision=workspace.requirement_revision,
    )

    assert workspace.content == "old text"
    assert workspace.requirement_content == ""
    assert saved.revision == 1
    assert saved.requirement_revision == 1
    assert chapter_repo.read_content(chapter.id) == "new text"
    assert len(chapter_repo.list_versions(chapter.id)) == 1
    reloaded = service.load_chapter(chapter.id)
    assert reloaded.requirement_content == "must happen"
    service.close_project()


def test_workspace_reports_stale_revision_without_overwriting_content(
    tmp_path: Path,
) -> None:
    project = ProjectRepository.create(tmp_path / "novel", "My Novel")
    chapter_repo = ChapterRepository(project)
    chapter = chapter_repo.create_chapter(
        project.list_volumes()[0].id,
        "Opening",
        "1",
        "old text",
    )
    service = ProjectWorkspaceService()
    service.open_project(project.layout.root)
    chapter_repo.save_content(chapter.id, "external", source="test", reason="stale")

    with pytest.raises(RuntimeError, match="revision"):
        service.save_chapter(chapter.id, "new text", expected_revision=0)

    assert chapter_repo.read_content(chapter.id) == "external"
    service.close_project()


def test_workspace_requires_open_project_before_operations() -> None:
    service = ProjectWorkspaceService()

    with pytest.raises(WorkspaceNotOpenError):
        service.volume_tree()


def test_workspace_creates_and_renames_chapters_and_volumes(tmp_path: Path) -> None:
    service = ProjectWorkspaceService()
    service.create_project(tmp_path / "novel", "My Novel")
    first_volume = service.volume_tree()[0]

    second_volume = service.create_volume("第二卷")
    chapter = service.create_chapter(second_volume.id, "新章节", "第 1 章")
    service.rename_volume(second_volume.id, "第二卷·风暴")
    service.rename_chapter(chapter.id, "风暴将至")

    tree = service.volume_tree()
    assert [volume.title for volume in tree] == [first_volume.title, "第二卷·风暴"]
    assert tree[1].chapters[0].title == "风暴将至"
    service.close_project()


def test_deleting_volume_moves_its_chapters_to_previous_volume(tmp_path: Path) -> None:
    service = ProjectWorkspaceService()
    service.create_project(tmp_path / "novel", "My Novel")
    first_volume = service.volume_tree()[0]
    second_volume = service.create_volume("第二卷")
    chapter = service.create_chapter(second_volume.id, "不会丢失", "第 1 章")

    target_volume_id = service.delete_volume(second_volume.id)

    tree = service.volume_tree()
    assert target_volume_id == first_volume.id
    assert len(tree) == 1
    assert tree[0].chapters[0].id == chapter.id
    assert service.load_chapter(chapter.id).title == "不会丢失"
    service.close_project()
