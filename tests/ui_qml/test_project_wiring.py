"""Frontend Wave F2: read-only real-project wiring through the facade."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QUrl

from ai_novel_studio.application.project_workspace_service import ProjectWorkspaceService
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


def test_save_in_project_mode_is_session_local_and_honest(tmp_path: Path) -> None:
    root = create_temp_project(tmp_path / "novel")
    facade = MockNovelStudioFacade()
    facade.openProject(str(root))

    facade.editorTextChanged("修改后的正文")
    assert facade.property("editorState") == "DIRTY"
    facade.requestSave()

    assert facade.property("editorState") == "CLEAN"
    assert facade.property("currentRevision") == 1  # unchanged: no disk write
    assert "F3" in facade.property("saveStatusText")


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
