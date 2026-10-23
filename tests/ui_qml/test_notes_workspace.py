import pytest
from PySide6.QtCore import QCoreApplication, QEvent, QMetaObject, QUrl
from PySide6.QtQml import QQmlApplicationEngine
from PySide6.QtQuick import QQuickWindow

from ai_novel_studio.infrastructure.storage.note_repository import NoteRepository
from ai_novel_studio.infrastructure.storage.project_repository import ProjectRepository
from ai_novel_studio.ui_qml.bootstrap import app_qml_path, register_frontend_types
from ai_novel_studio.ui_qml.bridge.mock_novel_studio_facade import MockNovelStudioFacade

from .test_outline_page import _find


@pytest.fixture
def notebook(tmp_path, qtbot):
    project = ProjectRepository.create(tmp_path / "novel", "笔记工作区")
    note = NoteRepository(project).create(
        "第二事件细纲", "# 细纲\n\n|人物|目标|\n|---|---|\n|林默|寻找旧信|", kind="OUTLINE"
    )
    facade = MockNovelStudioFacade()
    assert facade.openProject(str(project.layout.root)) == ""
    facade.setReduceMotion(True)
    engine = QQmlApplicationEngine()
    _, theme = register_frontend_types(engine, facade)
    warnings = []
    engine.warnings.connect(lambda values: warnings.extend(v.toString() for v in values))
    engine.load(QUrl.fromLocalFile(str(app_qml_path())))
    window = engine.rootObjects()[0]
    assert isinstance(window, QQuickWindow)
    yield project, note, facade, window, warnings
    facade.closeProject()
    engine.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)


def test_notes_are_a_top_level_mode_with_own_navigation_and_markdown(notebook):
    _, _, facade, window, warnings = notebook
    QMetaObject.invokeMethod(_find(window.contentItem(), "mode-notes"), "clicked")
    assert facade.activeNav == "notes"
    assert _find(window.contentItem(), "notesNavigator").isVisible()
    assert not _find(window.contentItem(), "chapterList").isVisible()
    assert "<table" in _find(window.contentItem(), "noteReadView").property("text")
    assert _find(window.contentItem(), "wordCountStatusChip").property("label") == "笔记"
    assert not warnings


def test_ui_saves_notes_and_leaving_notes_flushes_pending_edits(notebook):
    project, note, facade, window, warnings = notebook
    facade.setActiveNav("notes")
    QMetaObject.invokeMethod(_find(window.contentItem(), "noteSourceToggle"), "clicked")
    editor = _find(window.contentItem(), "noteEditor")
    editor.setProperty("text", "# 商讨后的细纲\n明确动机。")
    QMetaObject.invokeMethod(_find(window.contentItem(), "noteSaveButton"), "clicked")
    assert NoteRepository(project).read(note.id).content.endswith("明确动机。")
    editor.setProperty("text", "# 再次细化\n保留因果。")
    QMetaObject.invokeMethod(_find(window.contentItem(), "mode-writing"), "clicked")
    assert facade.activeNav == "writing"
    assert NoteRepository(project).read(note.id).content.endswith("保留因果。")
    assert not warnings


def test_new_note_dialog_creates_editable_note_and_picker_is_available_in_chat(notebook, qtbot):
    project, _, facade, window, warnings = notebook
    facade.setActiveNav("notes")
    QMetaObject.invokeMethod(_find(window.contentItem(), "noteNewButton"), "clicked")
    qtbot.waitUntil(lambda: _find(window.contentItem(), "noteNewTitle") is not None)
    _find(window.contentItem(), "noteNewTitle").setProperty("text", "文风注意事项")
    QMetaObject.invokeMethod(_find(window.contentItem(), "noteCreateConfirm"), "clicked")
    assert facade.notes.state["title"] == "文风注意事项"
    assert _find(window.contentItem(), "noteEditor").isVisible()
    assert len(NoteRepository(project).list_notes()) == 2
    facade.toggleAiDrawer(True)
    QMetaObject.invokeMethod(_find(window.contentItem(), "agentAttachmentButton"), "clicked")
    qtbot.waitUntil(lambda: _find(window.contentItem(), "noteInputPickerButton") is not None)
    QMetaObject.invokeMethod(_find(window.contentItem(), "noteInputPickerButton"), "clicked")
    qtbot.waitUntil(
        lambda: (
            _find(window.contentItem(), "noteInputPickerOptions") is not None
            and _find(window.contentItem(), "noteInputPickerOptions").isVisible()
        )
    )
    assert not warnings


def test_note_save_conflict_blocks_project_close_and_window_close(notebook):
    project, note, facade, window, _ = notebook
    facade.setActiveNav("notes")
    facade.notes.edit("不能丢失的本地笔记")
    NoteRepository(project).save(note.id, "外部新版", expected_revision=1)
    facade.setActiveNav("writing")
    assert facade.activeNav == "notes"
    facade.closeProject()
    assert facade.projectSource == "project"
    window.close()
    assert window.isVisible()
    assert facade.notes.state["text"] == "不能丢失的本地笔记"
    assert facade.notes.reload()
