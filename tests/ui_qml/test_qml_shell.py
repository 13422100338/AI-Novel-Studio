from pathlib import Path

from PySide6.QtCore import QUrl
from PySide6.QtQml import QQmlApplicationEngine
from pytestqt.qtbot import QtBot

from ai_novel_studio.ui_qml.bootstrap import app_qml_path, register_frontend_types
from ai_novel_studio.ui_qml.bridge.mock_novel_studio_facade import MockNovelStudioFacade
from ai_novel_studio.ui_qml.bridge.theme_provider import ThemeProvider


def _load_engine(
    qtbot: QtBot,
) -> tuple[QQmlApplicationEngine, MockNovelStudioFacade, ThemeProvider]:
    engine = QQmlApplicationEngine()
    engine.addImportPath(str(Path(app_qml_path()).parent))
    facade = MockNovelStudioFacade()
    theme = ThemeProvider()
    register_frontend_types(engine, facade, theme)
    engine.load(QUrl.fromLocalFile(str(app_qml_path())))
    assert engine.rootObjects(), "App.qml failed to load"
    return engine, facade, theme


def test_shell_loads_and_exposes_core_objects(qtbot: QtBot) -> None:
    engine, _, _ = _load_engine(qtbot)
    window = engine.rootObjects()[0]
    assert window.objectName() == "f1Window"
    for name in (
        "manuscriptEditor",
        "saveButton",
        "chapterList",
        "sidebarSearch",
        "aiDrawer",
        "themeButton",
        "motionButton",
    ):
        assert window.findChild(object, name) is not None, f"missing {name}"


def test_typing_marks_editor_dirty_and_save_clears(qtbot: QtBot) -> None:
    engine, facade, _ = _load_engine(qtbot)
    window = engine.rootObjects()[0]
    editor = window.findChild(object, "manuscriptEditor")
    editor.setProperty("text", "模拟输入的正文内容")
    assert facade.property("editorState") == "DIRTY"
    facade.requestSave()
    assert facade.property("editorState") == "CLEAN"
    assert facade.property("currentRevision") == 4


def test_draft_button_opens_drawer_with_suggestion(qtbot: QtBot) -> None:
    engine, facade, _ = _load_engine(qtbot)
    facade.requestDraft()
    assert facade.property("aiDrawerOpen") is True
    suggestions = facade.property("suggestions")
    assert suggestions.rowCount() == 1


def test_chapter_selection_updates_editor_text(qtbot: QtBot) -> None:
    engine, facade, _ = _load_engine(qtbot)
    window = engine.rootObjects()[0]
    editor = window.findChild(object, "manuscriptEditor")
    facade.selectChapter(5)
    assert facade.property("currentChapterId") == "chapter-4"
    assert "十二封信" in editor.property("text")
    assert facade.property("editorState") == "CLEAN"


def test_theme_toggle_changes_tokens(qtbot: QtBot) -> None:
    engine, _, theme = _load_engine(qtbot)
    theme.setTheme("dark")
    tokens = theme.property("tokens")
    assert tokens["color"]["bgCanvas"] == "#202124"
    theme.setTheme("light")
    assert theme.property("themeName") == "light"


def test_navigation_placeholder_page(qtbot: QtBot) -> None:
    engine, facade, _ = _load_engine(qtbot)
    facade.setActiveNav("settings")
    assert facade.property("activeNav") == "settings"
