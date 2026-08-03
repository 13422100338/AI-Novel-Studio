from pathlib import Path

from PySide6.QtCore import QMetaObject, QUrl
from PySide6.QtQml import QQmlApplicationEngine
from PySide6.QtQuick import QQuickItem
from pytestqt.qtbot import QtBot

from ai_novel_studio.ui_qml.bootstrap import app_qml_path, register_frontend_types
from ai_novel_studio.ui_qml.bridge.mock_novel_studio_facade import MockNovelStudioFacade
from ai_novel_studio.ui_qml.bridge.theme_provider import ThemeProvider

from .test_mock_facade import FakeDraftPort


def _create_temp_project(root: Path) -> Path:
    """Minimal real-project fixture (mirrors test_project_wiring)."""
    from ai_novel_studio.application.project_workspace_service import (
        ProjectWorkspaceService,
    )

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



def _find_quick_item(root: QQuickItem, name: str) -> QQuickItem | None:
    """Find a QML item by objectName through the QQuickItem hierarchy.

    QObject.findChild cannot see Repeater delegate items in PySide6; walking
    childItems() covers both regular items and delegated list content.
    """
    if root.objectName() == name:
        return root
    for child in root.childItems():
        found = _find_quick_item(child, name)
        if found is not None:
            return found
    return None


def _load_engine(
    qtbot: QtBot,
    facade: MockNovelStudioFacade | None = None,
) -> tuple[QQmlApplicationEngine, MockNovelStudioFacade, ThemeProvider]:
    engine = QQmlApplicationEngine()
    engine.addImportPath(str(Path(app_qml_path()).parent))
    facade = facade or MockNovelStudioFacade()
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


def test_sidebar_toggle_toggles_state_and_label(qtbot: QtBot) -> None:
    engine, _, _ = _load_engine(qtbot)
    window = engine.rootObjects()[0]
    toggle = window.findChild(object, "sidebarToggle")
    assert toggle is not None
    assert window.findChild(object, "sidebarHost") is not None

    assert window.property("sidebarVisible") is True
    assert toggle.property("text") == "收起侧栏"

    QMetaObject.invokeMethod(toggle, "clicked")
    assert window.property("sidebarVisible") is False
    assert toggle.property("text") == "展开侧栏"

    QMetaObject.invokeMethod(toggle, "clicked")
    assert window.property("sidebarVisible") is True
    assert toggle.property("text") == "收起侧栏"


def test_navigation_rail_button_switches_page(qtbot: QtBot) -> None:
    engine, facade, _ = _load_engine(qtbot)
    window = engine.rootObjects()[0]
    memory_button = _find_quick_item(window.contentItem(), "nav-memory")
    assert memory_button is not None
    QMetaObject.invokeMethod(memory_button, "clicked")
    assert facade.property("activeNav") == "memory"


def test_sidebar_search_filters_chapter_list(qtbot: QtBot) -> None:
    engine, facade, _ = _load_engine(qtbot)
    window = engine.rootObjects()[0]
    search = window.findChild(object, "sidebarSearch")
    assert search is not None
    search.setProperty("text", "灯塔")
    model = facade.property("chapters")
    assert model.rowCount() == 2
    search.setProperty("text", "")
    assert model.rowCount() == 7


def test_theme_button_cycles_theme(qtbot: QtBot) -> None:
    engine, _, theme = _load_engine(qtbot)
    window = engine.rootObjects()[0]
    theme_button = window.findChild(object, "themeButton")
    assert theme.property("themeName") == "paper"
    QMetaObject.invokeMethod(theme_button, "clicked")
    assert theme.property("themeName") == "light"
    QMetaObject.invokeMethod(theme_button, "clicked")
    assert theme.property("themeName") == "dark"


def test_draft_button_opens_drawer(qtbot: QtBot) -> None:
    engine, facade, _ = _load_engine(qtbot)
    window = engine.rootObjects()[0]
    draft_button = window.findChild(object, "draftButton")
    start_button = window.findChild(object, "startGenerationButton")
    assert draft_button is not None
    assert start_button is not None

    QMetaObject.invokeMethod(draft_button, "clicked")
    dialog = window.findChild(object, "generationConfigDialog")
    assert dialog is not None
    qtbot.waitUntil(lambda: dialog.property("visible") is True, timeout=5000)
    QMetaObject.invokeMethod(start_button, "clicked")

    assert facade.property("aiDrawerOpen") is True
    assert facade.property("suggestions").rowCount() == 1


def test_drawer_close_button_closes_drawer(qtbot: QtBot) -> None:
    engine, facade, _ = _load_engine(qtbot)
    window = engine.rootObjects()[0]
    facade.requestDraft()
    assert facade.property("aiDrawerOpen") is True
    close_button = window.findChild(object, "drawerCloseButton")
    assert close_button is not None
    QMetaObject.invokeMethod(close_button, "clicked")
    assert facade.property("aiDrawerOpen") is False


def test_project_controls_exist_in_sidebar(qtbot: QtBot) -> None:
    engine, _, _ = _load_engine(qtbot)
    window = engine.rootObjects()[0]
    for name in ("openProjectButton", "resetDemoButton", "projectOpenDialog", "projectMessage"):
        assert window.findChild(object, name) is not None, f"missing {name}"


def test_real_project_loads_into_editor(qtbot: QtBot, tmp_path: Path) -> None:
    root = _create_temp_project(tmp_path / "novel")
    engine, facade, _ = _load_engine(qtbot)
    window = engine.rootObjects()[0]
    editor = window.findChild(object, "manuscriptEditor")

    error = facade.openProject(str(root))

    assert error == ""
    assert "这是测试正文" in editor.property("text")
    assert facade.property("projectSource") == "project"


def test_reset_demo_restores_mock_editor(qtbot: QtBot, tmp_path: Path) -> None:
    root = _create_temp_project(tmp_path / "novel")
    engine, facade, _ = _load_engine(qtbot)
    window = engine.rootObjects()[0]
    editor = window.findChild(object, "manuscriptEditor")
    facade.openProject(str(root))

    facade.closeProject()

    assert facade.property("projectSource") == "mock"
    assert "清晨的雾港" in editor.property("text")


def test_save_conflict_shows_reload_button_and_recovers(
    qtbot: QtBot, tmp_path: Path
) -> None:
    from ai_novel_studio.infrastructure.storage.chapter_repository import (
        ChapterRepository,
    )
    from ai_novel_studio.infrastructure.storage.project_repository import (
        ProjectRepository,
    )

    root = _create_temp_project(tmp_path / "novel")
    engine, facade, _ = _load_engine(qtbot)
    window = engine.rootObjects()[0]
    editor = window.findChild(object, "manuscriptEditor")
    save_button = window.findChild(object, "saveButton")
    reload_button = window.findChild(object, "reloadButton")
    facade.openProject(str(root))
    chapter_id = facade.property("currentChapterId")

    project = ProjectRepository.open(root)
    ChapterRepository(project).save_content(
        chapter_id,
        "外部写入的正文",
        source="user_edit",
        reason="external edit",
        expected_revision=1,
    )
    editor.setProperty("text", "本地编辑的正文")
    assert facade.property("editorState") == "DIRTY"

    QMetaObject.invokeMethod(save_button, "clicked")
    assert facade.property("editorState") == "CONFLICT"
    assert reload_button.property("visible") is True

    QMetaObject.invokeMethod(reload_button, "clicked")
    assert facade.property("editorState") == "CLEAN"
    assert "外部写入的正文" in editor.property("text")
    assert facade.property("currentRevision") == 2


def test_project_draft_button_uses_injected_port(
    qtbot: QtBot, tmp_path: Path
) -> None:
    root = _create_temp_project(tmp_path / "novel")
    port = FakeDraftPort(draft_text="AI 生成的草稿正文。")
    facade = MockNovelStudioFacade(draft_port=port)
    facade.openProject(str(root))
    engine, facade, _ = _load_engine(qtbot, facade)
    window = engine.rootObjects()[0]
    editor = window.findChild(object, "manuscriptEditor")
    draft_button = window.findChild(object, "draftButton")
    start_button = window.findChild(object, "startGenerationButton")

    QMetaObject.invokeMethod(draft_button, "clicked")
    qtbot.waitUntil(
        lambda: window.findChild(object, "startGenerationButton") is not None
        and window.findChild(object, "generationConfigDialog").property("visible"),
        timeout=5000,
    )
    QMetaObject.invokeMethod(start_button, "clicked")
    qtbot.waitUntil(
        lambda: facade.property("suggestions").rowCount() == 1,
        timeout=5000,
    )

    assert facade.property("aiDrawerOpen") is True
    assert facade.property("suggestions").rowCount() == 1
    assert facade.property("draftStatus") == "COMPLETED"

    facade.acceptSuggestion(0)
    assert "AI 生成的草稿正文" in editor.property("text")
    assert facade.property("currentRevision") == 7
    assert facade.property("editorState") == "CLEAN"


def test_generation_config_dialog_applies_values_before_start(
    qtbot: QtBot,
) -> None:
    facade = MockNovelStudioFacade()
    engine, facade, _ = _load_engine(qtbot, facade)
    window = engine.rootObjects()[0]
    dialog = window.findChild(object, "generationConfigDialog")
    assert dialog is not None
    draft_button = window.findChild(object, "draftButton")
    start_button = window.findChild(object, "startGenerationButton")

    QMetaObject.invokeMethod(draft_button, "clicked")
    qtbot.waitUntil(lambda: dialog.property("visible") is True, timeout=5000)

    target_spin = dialog.findChild(object, "targetWordsSpin")
    token_spin = dialog.findChild(object, "tokenLimitSpin")
    mode_combo = dialog.findChild(object, "modeCombo")
    audit_combo = dialog.findChild(object, "auditCombo")
    assert target_spin is not None and token_spin is not None
    assert mode_combo is not None and audit_combo is not None

    target_spin.setProperty("value", 2500)
    token_spin.setProperty("value", 4096)
    mode_combo.setProperty("currentIndex", 1)
    audit_combo.setProperty("currentIndex", 1)
    QMetaObject.invokeMethod(start_button, "clicked")

    assert facade.property("generationTargetWords") == 2500
    assert facade.property("generationOutputTokenLimit") == 4096
    assert facade.property("generationMode") == "STANDARD"
    assert facade.property("generationAuditPolicy") == "STANDARD"
    # Demo mode: starting generation adds a mock suggestion.
    qtbot.waitUntil(
        lambda: facade.property("suggestions").rowCount() == 1,
        timeout=5000,
    )


def test_draft_three_view_buttons_and_switch(qtbot: QtBot, tmp_path: Path) -> None:
    root = _create_temp_project(tmp_path / "novel")
    port = FakeDraftPort(draft_text="这是测试正文。\n\nAI 新增的段落。")
    facade = MockNovelStudioFacade(draft_port=port)
    facade.openProject(str(root))
    engine, facade, _ = _load_engine(qtbot, facade)
    window = engine.rootObjects()[0]
    facade.requestDraft()
    qtbot.waitUntil(
        lambda: facade.property("suggestions").rowCount() == 1,
        timeout=5000,
    )

    current_button = window.findChild(object, "viewCurrentButton")
    draft_button = window.findChild(object, "viewDraftButton")
    diff_button = window.findChild(object, "viewDiffButton")
    assert current_button is not None
    assert draft_button is not None
    assert diff_button is not None
    assert facade.property("draftView") == "draft"

    QMetaObject.invokeMethod(current_button, "clicked")
    assert facade.property("draftView") == "current"
    QMetaObject.invokeMethod(diff_button, "clicked")
    assert facade.property("draftView") == "diff"


def test_diff_view_accept_block_updates_editor(qtbot: QtBot, tmp_path: Path) -> None:
    root = _create_temp_project(tmp_path / "novel")
    port = FakeDraftPort(draft_text="这是测试正文。\n\nAI 重写的第二段。")
    facade = MockNovelStudioFacade(draft_port=port)
    facade.openProject(str(root))
    engine, facade, _ = _load_engine(qtbot, facade)
    window = engine.rootObjects()[0]
    editor = window.findChild(object, "manuscriptEditor")
    facade.requestDraft()
    qtbot.waitUntil(
        lambda: facade.property("suggestions").rowCount() == 1,
        timeout=5000,
    )
    facade.setDraftView("diff")
    diff_list = window.findChild(object, "diffList")
    assert diff_list is not None
    diff_model = facade.property("draftDiff")
    qtbot.waitUntil(lambda: diff_model.rowCount() > 0, timeout=5000)

    # Delegate buttons are reachable through childItems; click the accept
    # button on the replaced block to verify the editor updates.
    qtbot.waitUntil(
        lambda: _find_quick_item(window.contentItem(), "acceptDiffButton") is not None,
        timeout=5000,
    )
    from ai_novel_studio.ui_qml.bridge.models.draft_diff_model import ROLE_BLOCK_ID, ROLE_KIND

    replaced_id = None
    for row in range(diff_model.rowCount()):
        if diff_model.data(diff_model.index(row), ROLE_KIND) == "replaced":
            replaced_id = diff_model.data(diff_model.index(row), ROLE_BLOCK_ID)
            break
    assert replaced_id is not None
    facade.acceptDiffBlock(replaced_id)

    assert "AI 重写的第二段" in editor.property("text")
    assert facade.property("editorState") == "DIRTY"


def test_usage_chips_visible_and_update_after_generation(
    qtbot: QtBot, tmp_path: Path
) -> None:
    root = _create_temp_project(tmp_path / "novel")
    port = FakeDraftPort(draft_text="草稿正文")
    facade = MockNovelStudioFacade(draft_port=port)
    facade.openProject(str(root))
    engine, facade, _ = _load_engine(qtbot, facade)
    window = engine.rootObjects()[0]

    for name in ("usageTokensChip", "usageCostChip", "usageCacheChip"):
        assert window.findChild(object, name) is not None, f"missing {name}"
    assert window.findChild(object, "usageTokensChip").property("value") == "0 / 0"

    facade.requestDraft()
    qtbot.waitUntil(
        lambda: facade.property("draftStatus") == "COMPLETED",
        timeout=5000,
    )

    assert window.findChild(object, "usageTokensChip").property("value") == "1.2K / 800"
    assert window.findChild(object, "usageCostChip").property("value") == "¥0.018"
    assert window.findChild(object, "usageCacheChip").property("value") == "缓存 600"
    tokens_chip = window.findChild(object, "usageTokensChip")
    assert tokens_chip.property("tooltipText") == "输入 / 输出 · 1 次调用"


def test_overview_pages_exist_and_show_counts(qtbot: QtBot, tmp_path: Path) -> None:
    root = _create_temp_project(tmp_path / "novel")
    facade = MockNovelStudioFacade()
    facade.openProject(str(root))
    engine, facade, _ = _load_engine(qtbot, facade)
    window = engine.rootObjects()[0]

    for page in ("charactersPage", "memoryPage", "auditPage"):
        assert window.findChild(object, page) is not None, f"missing {page}"

    facade.setActiveNav("characters")
    assert facade.property("activeNav") == "characters"
    characters_page = window.findChild(object, "charactersPage")
    assert characters_page.property("visible") is True
    count_chip = window.findChild(object, "charactersPageCount")
    assert count_chip is not None
    assert count_chip.property("value") == "0 人"


def test_readonly_lists_exist_and_show_empty_state(
    qtbot: QtBot, tmp_path: Path
) -> None:
    root = _create_temp_project(tmp_path / "novel")
    facade = MockNovelStudioFacade()
    facade.openProject(str(root))
    engine, facade, _ = _load_engine(qtbot, facade)
    window = engine.rootObjects()[0]

    for name in ("charactersList", "memoryList", "auditList"):
        assert window.findChild(object, name) is not None, f"missing {name}"

    facade.setActiveNav("memory")
    memory_list = window.findChild(object, "memoryList")
    assert memory_list is not None
    assert memory_list.property("count") == 0
    assert facade.property("memoryViews").rowCount() == 0


def test_character_detail_panel_shows_after_selection(
    qtbot: QtBot, tmp_path: Path
) -> None:
    from .test_readonly_views import create_project_with_character

    root, _ = create_project_with_character(tmp_path)
    facade = MockNovelStudioFacade()
    facade.openProject(str(root))
    facade.selectChapter(1)
    engine, facade, _ = _load_engine(qtbot, facade)
    window = engine.rootObjects()[0]
    detail = window.findChild(object, "characterDetail")
    assert detail is not None

    facade.setActiveNav("characters")
    facade.selectCharacter(0)

    assert facade.property("characterDetailVisible") is True
    qtbot.waitUntil(lambda: detail.property("visible") is True, timeout=5000)
    journey_list = window.findChild(object, "characterJourneyList")
    assert journey_list is not None
    assert facade.property("characterJourney").rowCount() == 1

    close_button = window.findChild(object, "closeCharacterDetailButton")
    assert close_button is not None
    from PySide6.QtCore import QMetaObject

    QMetaObject.invokeMethod(close_button, "clicked")
    assert facade.property("characterDetailVisible") is False
