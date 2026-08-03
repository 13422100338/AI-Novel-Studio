"""Frontend Wave F2/F3: real-project wiring through the facade."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QUrl

from ai_novel_studio.application.project_workspace_service import ProjectWorkspaceService
from ai_novel_studio.infrastructure.storage.chapter_repository import ChapterRepository
from ai_novel_studio.infrastructure.storage.project_repository import ProjectRepository
from ai_novel_studio.ui_qml.bridge.mock_novel_studio_facade import MockNovelStudioFacade


def create_temp_project(root: Path) -> Path:
    """Create a small real project fixture with one chapter of content."""
    service = ProjectWorkspaceService()
    service.create_project(root, "测试小说")
    volume = service.volume_tree()[0]
    chapter = service.create_chapter(volume.id, "第一章 起风", "第 1 章")
    service.save_chapter(
        chapter.id,
        "这是测试正文。\n\n第二段。",
        expected_revision=chapter.revision,
    )
    service.close_project()
    return root


def _external_edit(root: Path, chapter_id: str, content: str, expected_revision: int) -> None:
    """Simulate an external writer changing the chapter on disk.

    The project writer lock is exclusive per open, so an external change is
    applied through the chapter repository directly (same persisted store the
    workspace writes to). This is test fixture code only.
    """
    project = ProjectRepository.open(root)
    ChapterRepository(project).save_content(
        chapter_id,
        content,
        source="user_edit",
        reason="external edit",
        expected_revision=expected_revision,
    )


def test_open_project_loads_real_tree_and_document(tmp_path: Path) -> None:
    root = create_temp_project(tmp_path / "novel")
    facade = MockNovelStudioFacade()

    error = facade.openProject(str(root))

    assert error == ""
    assert facade.property("projectSource") == "project"
    assert facade.property("projectTitle") == "测试小说"
    assert facade.property("chapterCount") == 1
    volume = facade.volumes()[0]
    assert volume.chapters[0].title == "第一章 起风"
    assert volume.chapters[0].declared_number == "第 1 章"

    facade.selectChapter(1)
    assert facade.property("currentChapterId") == volume.chapters[0].id
    assert facade.property("currentChapterBody") == "这是测试正文。\n\n第二段。"
    assert facade.property("currentRevision") == 1
    assert facade.property("editorState") == "CLEAN"


def test_open_project_failure_reports_error_and_keeps_mock(tmp_path: Path) -> None:
    facade = MockNovelStudioFacade()

    error = facade.openProject(str(tmp_path / "missing"))

    assert error != ""
    assert "打开项目失败" in error
    assert facade.property("projectSource") == "mock"
    assert facade.property("projectTitle") == "雾港来信"


def test_close_project_restores_mock_state(tmp_path: Path) -> None:
    root = create_temp_project(tmp_path / "novel")
    facade = MockNovelStudioFacade()
    facade.openProject(str(root))

    facade.closeProject()

    assert facade.property("projectSource") == "mock"
    assert facade.property("projectTitle") == "雾港来信"
    assert facade.property("currentChapterId") == "chapter-1"
    assert "清晨的雾港" in facade.property("currentChapterBody")
    assert facade.property("currentRevision") == 3


def test_save_persists_to_disk_and_bumps_revision(tmp_path: Path) -> None:
    root = create_temp_project(tmp_path / "novel")
    facade = MockNovelStudioFacade()
    facade.openProject(str(root))
    chapter_id = facade.property("currentChapterId")

    facade.editorTextChanged("修改后的正文")
    assert facade.property("editorState") == "DIRTY"
    facade.requestSave()

    assert facade.property("editorState") == "CLEAN"
    assert facade.property("currentRevision") == 2
    assert "修订 2" in facade.property("saveStatusText")

    facade.closeProject()
    verify = ProjectWorkspaceService()
    verify.open_project(root)
    workspace = verify.load_chapter(chapter_id)
    assert workspace.content == "修改后的正文"
    assert workspace.revision == 2
    verify.close_project()


def test_save_detects_stale_revision_conflict(tmp_path: Path) -> None:
    root = create_temp_project(tmp_path / "novel")
    facade = MockNovelStudioFacade()
    facade.openProject(str(root))
    chapter_id = facade.property("currentChapterId")

    _external_edit(root, chapter_id, "外部写入的正文", expected_revision=1)
    facade.editorTextChanged("本地编辑的正文")
    facade.requestSave()

    assert facade.property("editorState") == "CONFLICT"
    assert "修订冲突" in facade.property("saveStatusText")
    assert "未覆盖" in facade.property("saveStatusText")
    # Local edits were not written over the external content.
    assert facade.property("currentChapterBody") == "本地编辑的正文"


def test_reload_chapter_recovers_after_conflict(tmp_path: Path) -> None:
    root = create_temp_project(tmp_path / "novel")
    facade = MockNovelStudioFacade()
    facade.openProject(str(root))
    chapter_id = facade.property("currentChapterId")
    _external_edit(root, chapter_id, "外部写入的正文", expected_revision=1)
    facade.editorTextChanged("本地编辑的正文")
    facade.requestSave()
    assert facade.property("editorState") == "CONFLICT"

    facade.reloadChapter()

    assert facade.property("editorState") == "CLEAN"
    assert facade.property("currentRevision") == 2
    assert facade.property("currentChapterBody") == "外部写入的正文"
    assert "重新载入" in facade.property("saveStatusText")


def test_reload_chapter_is_noop_outside_conflict(tmp_path: Path) -> None:
    root = create_temp_project(tmp_path / "novel")
    facade = MockNovelStudioFacade()
    facade.openProject(str(root))

    facade.reloadChapter()

    assert facade.property("editorState") == "CLEAN"
    assert facade.property("currentRevision") == 1


def test_editing_during_conflict_keeps_conflict_state(tmp_path: Path) -> None:
    root = create_temp_project(tmp_path / "novel")
    facade = MockNovelStudioFacade()
    facade.openProject(str(root))
    chapter_id = facade.property("currentChapterId")
    _external_edit(root, chapter_id, "外部写入的正文", expected_revision=1)
    facade.editorTextChanged("本地编辑的正文")
    facade.requestSave()
    assert facade.property("editorState") == "CONFLICT"

    facade.editorTextChanged("冲突期间继续打字")

    assert facade.property("editorState") == "CONFLICT"


def test_open_project_twice_replaces_previous_workspace(tmp_path: Path) -> None:
    first = create_temp_project(tmp_path / "first")
    second = create_temp_project(tmp_path / "second")
    facade = MockNovelStudioFacade()

    assert facade.openProject(str(first)) == ""
    assert facade.openProject(str(second)) == ""

    assert facade.property("projectSource") == "project"
    assert facade.property("chapterCount") == 1
    assert facade.volumes()[0].chapters[0].title == "第一章 起风"


def test_open_project_from_url_uses_local_file_path(tmp_path: Path) -> None:
    root = create_temp_project(tmp_path / "novel")
    facade = MockNovelStudioFacade()

    error = facade.openProjectFromUrl(QUrl.fromLocalFile(str(root)))

    assert error == ""
    assert facade.property("projectSource") == "project"


def test_open_project_from_url_accepts_plain_string(tmp_path: Path) -> None:
    root = create_temp_project(tmp_path / "novel")
    facade = MockNovelStudioFacade()

    error = facade.openProjectFromUrl(str(root))

    assert error == ""
    assert facade.property("projectSource") == "project"
