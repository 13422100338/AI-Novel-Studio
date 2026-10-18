"""Frontend Wave F2/F3: real-project wiring through the facade."""

from __future__ import annotations

import pytest

pytest.importorskip("ai_novel_studio.application")

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


def test_open_project_failure_reports_error_and_keeps_empty(tmp_path: Path) -> None:
    facade = MockNovelStudioFacade()

    error = facade.openProject(str(tmp_path / "missing"))

    assert error != ""
    assert "打开项目失败" in error
    assert facade.property("projectSource") == "empty"
    assert facade.property("projectTitle") == "未打开项目"


def test_close_project_returns_to_empty_state(tmp_path: Path) -> None:
    root = create_temp_project(tmp_path / "novel")
    facade = MockNovelStudioFacade()
    facade.openProject(str(root))

    facade.closeProject()

    assert facade.property("projectSource") == "empty"
    assert facade.property("projectTitle") == "未打开项目"
    assert facade.property("chapterCount") == 0
    assert facade.property("currentChapterId") == ""
    assert facade.property("currentChapterBody") == ""
    assert facade.property("currentRevision") == 0


def _dir_bytes(root: Path) -> dict[str, bytes]:
    return {
        item.relative_to(root).as_posix(): item.read_bytes()
        for item in sorted(root.rglob("*"))
        if item.is_file()
    }


def test_create_project_from_url_converts_to_local_path(tmp_path: Path) -> None:
    from PySide6.QtCore import QUrl

    facade = MockNovelStudioFacade()

    error = facade.createProjectFromUrl(
        QUrl.fromLocalFile(str(tmp_path)), "URL新书"
    )

    assert error == ""
    assert facade.property("projectSource") == "project"
    assert facade.property("projectTitle") == "URL新书"
    target = tmp_path / "URL新书"
    assert target.is_dir()
    assert "file:" not in str(facade.property("projectPath"))


def test_create_project_from_url_rejects_non_local_url(tmp_path: Path) -> None:
    from PySide6.QtCore import QUrl

    facade = MockNovelStudioFacade()

    assert facade.createProjectFromUrl(QUrl("https://example.com/x"), "书") != ""
    assert facade.createProjectFromUrl(QUrl(), "书") != ""
    assert facade.property("projectSource") == "empty"
    assert not (tmp_path / "书").exists()


def test_create_project_sanitizes_failure_message(
    tmp_path: Path, monkeypatch
) -> None:
    from ai_novel_studio.application.project_workspace_service import (
        ProjectWorkspaceService,
    )

    def exploding_create(self, root, title):  # type: ignore[no-untyped-def]
        raise RuntimeError(
            f"sqlite3.OperationalError at {root}: SELECT * FROM chapters "
            "-- 正文标记 secret-body-marker"
        )

    monkeypatch.setattr(
        ProjectWorkspaceService, "create_project", exploding_create
    )
    facade = MockNovelStudioFacade()

    error = facade.createProject(str(tmp_path), "失败书")

    assert error != ""
    assert "失败" in error
    assert str(tmp_path) not in error
    assert "sqlite3" not in error.lower()
    assert "SELECT" not in error
    assert "secret-body-marker" not in error


def test_create_project_creates_reopenable_project(tmp_path: Path) -> None:
    facade = MockNovelStudioFacade()

    error = facade.createProject(str(tmp_path), "新书")

    assert error == ""
    assert facade.property("projectSource") == "project"
    assert facade.property("projectTitle") == "新书"
    target = tmp_path / "新书"
    assert target.is_dir()
    # The new project loads its default empty volume.
    assert facade.property("chapterCount") == 0
    assert len(facade.volumes()) == 1

    # The facade keeps the writer lock; release it before re-opening.
    facade.closeProject()
    assert facade.property("projectSource") == "empty"
    verify = ProjectWorkspaceService()
    verify.open_project(target)
    assert verify.summary().title == "新书"
    verify.close_project()


def test_create_project_rejects_existing_directory_fail_closed(
    tmp_path: Path,
) -> None:
    target = tmp_path / "已有"
    target.mkdir()
    (target / "existing.txt").write_bytes(b"keep-me-bytes")
    before = _dir_bytes(target)
    facade = MockNovelStudioFacade()

    error = facade.createProject(str(tmp_path), "已有")

    assert error != ""
    assert facade.property("projectSource") == "empty"
    assert _dir_bytes(target) == before


def test_create_project_rejects_existing_empty_directory(tmp_path: Path) -> None:
    (tmp_path / "空目录").mkdir()
    facade = MockNovelStudioFacade()

    error = facade.createProject(str(tmp_path), "空目录")

    assert error != ""
    assert facade.property("projectSource") == "empty"


def test_create_project_validates_title_and_parent(tmp_path: Path) -> None:
    facade = MockNovelStudioFacade()

    assert facade.createProject("", "书名") != ""
    assert facade.createProject(str(tmp_path), "   ") != ""
    assert facade.createProject(str(tmp_path), "a/b") != ""
    assert facade.property("projectSource") == "empty"


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


def test_save_from_editor_persists_and_bumps_revision(tmp_path: Path) -> None:
    root = create_temp_project(tmp_path / "novel")
    facade = MockNovelStudioFacade()
    facade.openProject(str(root))
    chapter_id = facade.property("currentChapterId")

    facade.saveFromEditor(chapter_id, 1, "来自 WebEngine 编辑器的正文")

    assert facade.property("editorState") == "CLEAN"
    assert facade.property("currentRevision") == 2
    assert facade.property("currentChapterBody") == "来自 WebEngine 编辑器的正文"

    facade.closeProject()
    verify = ProjectWorkspaceService()
    verify.open_project(root)
    workspace = verify.load_chapter(chapter_id)
    assert workspace.content == "来自 WebEngine 编辑器的正文"
    assert workspace.revision == 2
    verify.close_project()


def test_save_from_editor_rejects_wrong_chapter(tmp_path: Path) -> None:
    root = create_temp_project(tmp_path / "novel")
    facade = MockNovelStudioFacade()
    facade.openProject(str(root))

    facade.saveFromEditor("wrong-chapter", 1, "正文")

    assert "不一致" in facade.property("saveStatusText")
    assert facade.property("editorState") == "CLEAN"


def test_save_from_editor_stale_revision_enters_conflict(tmp_path: Path) -> None:
    root = create_temp_project(tmp_path / "novel")
    facade = MockNovelStudioFacade()
    facade.openProject(str(root))
    chapter_id = facade.property("currentChapterId")
    _external_edit(root, chapter_id, "外部写入", expected_revision=1)

    facade.saveFromEditor(chapter_id, 1, "编辑器正文")

    assert facade.property("editorState") == "CONFLICT"
    assert "修订" in facade.property("saveStatusText")


def test_save_from_editor_emits_revision_for_next_save(tmp_path: Path) -> None:
    """After a successful editor save the next save uses the new revision."""
    root = create_temp_project(tmp_path / "novel")
    facade = MockNovelStudioFacade()
    facade.openProject(str(root))
    chapter_id = facade.property("currentChapterId")
    revisions: list[int] = []
    facade.editorRevisionChanged.connect(revisions.append)

    facade.saveFromEditor(chapter_id, 1, "第一次保存")
    assert facade.property("currentRevision") == 2
    assert revisions == [2]

    facade.saveFromEditor(chapter_id, 2, "第二次保存")
    assert facade.property("currentRevision") == 3
    assert revisions == [2, 3]
    assert facade.property("editorState") == "CLEAN"


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


def test_facade_creates_volume_and_chapter_in_real_project(tmp_path: Path) -> None:
    facade = MockNovelStudioFacade()
    assert facade.createProject(str(tmp_path), "结构测试") == ""
    assert facade.property("chapterCount") == 0

    assert facade.createVolume("第二卷") == ""
    assert facade.createChapter("第一章 起笔", "第1章") == ""

    assert facade.property("chapterCount") == 1
    assert facade.property("currentChapterTitle") == "第一章 起笔"
    assert facade.property("currentChapterBody") == ""
    assert facade.property("currentVolumeTitle") == "第二卷"

    facade.closeProject()
    verify = ProjectWorkspaceService()
    verify.open_project(tmp_path / "结构测试")
    volumes = verify.volume_tree()
    assert len(volumes) == 2
    assert volumes[1].title == "第二卷"
    assert [chapter.title for chapter in volumes[1].chapters] == ["第一章 起笔"]
    verify.close_project()


def test_facade_imports_local_markdown_into_open_project(tmp_path: Path) -> None:
    source = tmp_path / "existing.md"
    source.write_text(
        "# 第一卷 旧城\n\n"
        "# 第1章 重逢\n\n"
        "重逢发生在雨夜。\n\n"
        "# 第2章 来信\n\n"
        "来信没有署名。",
        encoding="utf-8",
    )
    facade = MockNovelStudioFacade()
    assert facade.createProject(str(tmp_path), "导入测试") == ""

    error = facade.importManuscriptFromUrl(QUrl.fromLocalFile(str(source)))

    assert error == ""
    assert facade.property("chapterCount") == 2
    assert facade.property("currentChapterTitle") == "重逢"
    assert facade.property("currentChapterBody") == "重逢发生在雨夜。"


def test_facade_rejects_non_local_manuscript_import(tmp_path: Path) -> None:
    facade = MockNovelStudioFacade()
    assert facade.createProject(str(tmp_path), "导入边界") == ""

    error = facade.importManuscriptFromUrl(QUrl("https://example.com/book.md"))

    assert error == "请选择本地 Markdown 或 TXT 文件"
    assert facade.property("chapterCount") == 0


def test_facade_counts_and_deletes_only_empty_chapters(tmp_path: Path) -> None:
    facade = MockNovelStudioFacade()
    assert facade.createProject(str(tmp_path), "空章清理") == ""
    assert facade.createChapter("保留章", "第1章") == ""
    facade.editorTextChanged("应当保留的正文。")
    facade.requestSave()
    assert facade.createChapter("空章一", "第2章") == ""
    assert facade.createChapter("空章二", "第3章") == ""

    assert facade.emptyChapterCount() == 2
    assert facade.deleteEmptyChapters() == ""

    assert facade.property("chapterCount") == 1
    assert facade.property("currentChapterTitle") == "保留章"
    assert facade.property("currentChapterBody") == "应当保留的正文。"
