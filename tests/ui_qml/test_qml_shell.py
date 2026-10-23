import hashlib
import json
from pathlib import Path

import pytest
from PySide6.QtCore import QByteArray, QCoreApplication, QEvent, QMetaObject, QUrl
from PySide6.QtQml import QQmlApplicationEngine
from PySide6.QtQuick import QQuickItem
from pytestqt.qtbot import QtBot

from ai_novel_studio.application.selection_patch import (
    ANCHOR_CODEPOINTS,
    SCHEMA_VERSION,
)
from ai_novel_studio.ui_qml.bootstrap import app_qml_path, register_frontend_types
from ai_novel_studio.ui_qml.bridge.backend_availability import BACKEND_AVAILABLE
from ai_novel_studio.ui_qml.bridge.dtos import AgentTimelineItemDto
from ai_novel_studio.ui_qml.bridge.mock_novel_studio_facade import MockNovelStudioFacade
from ai_novel_studio.ui_qml.bridge.theme_provider import ThemeProvider

from .test_mock_facade import FakeDraftPort

_ACTIVE_ENGINES: list[QQmlApplicationEngine] = []
_ACTIVE_CONTEXTS: list[tuple[MockNovelStudioFacade, ThemeProvider]] = []


def _register_frontend_context(
    engine: QQmlApplicationEngine, facade: MockNovelStudioFacade, theme: ThemeProvider
) -> None:
    # QML context properties do not own their Python QObjects.
    _ACTIVE_CONTEXTS.append((facade, theme))
    register_frontend_types(engine, facade, theme)


def _selection_payload(source: str, selected: str) -> str:
    start = source.index(selected)
    end = start + len(selected)

    def span(span_start: int, span_end: int) -> dict[str, object]:
        text = source[span_start:span_end]
        return {
            "start": span_start,
            "end": span_end,
            "text": text,
            "text_hash": hashlib.sha256(text.encode("utf-8")).hexdigest(),
        }

    return json.dumps(
        {
            "schema_version": SCHEMA_VERSION,
            "chapter_id": "chapter-1",
            "base_revision": 3,
            "base_source_hash": hashlib.sha256(source.encode("utf-8")).hexdigest(),
            "selection": span(start, end),
            "before_anchor": span(max(0, start - ANCHOR_CODEPOINTS), start),
            "after_anchor": span(
                end,
                min(len(source), end + ANCHOR_CODEPOINTS),
            ),
        },
        ensure_ascii=False,
    )


@pytest.fixture(autouse=True)
def _delete_active_engines() -> None:
    """Destroy QML engines deterministically after each test.

    Leaving engines alive across tests lets Qt deliver queued model/view
    events during an unrelated test, which surfaces as spurious
    QAbstractListModel errors in teardown.
    """
    yield
    for engine in _ACTIVE_ENGINES:
        engine.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    _ACTIVE_ENGINES.clear()
    _ACTIVE_CONTEXTS.clear()


def _create_temp_project(root: Path) -> Path:
    """Minimal real-project fixture (mirrors test_project_wiring)."""
    if not BACKEND_AVAILABLE:
        import pytest

        pytest.skip("needs backend project workspace")
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


def _find_visible_quick_item(root: QQuickItem, name: str) -> QQuickItem | None:
    """Find the first visible QML item with the given objectName."""
    if root.objectName() == name and root.property("visible") is True:
        return root
    for child in root.childItems():
        found = _find_visible_quick_item(child, name)
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
    _register_frontend_context(engine, facade, theme)
    engine.load(QUrl.fromLocalFile(str(app_qml_path())))
    assert engine.rootObjects(), "App.qml failed to load"
    _ACTIVE_ENGINES.append(engine)
    return engine, facade, theme


def test_shell_loads_and_exposes_core_objects(qtbot: QtBot) -> None:
    engine, _, _ = _load_engine(qtbot)
    window = engine.rootObjects()[0]
    assert window.objectName() == "f1Window"
    for name in (
        "manuscriptEditor",
        "chapterSaveButton",
        "chapterList",
        "sidebarSearch",
        "agentDock",
        "chapterReloadButton",
        "statusMoreButton",
    ):
        assert window.findChild(object, name) is not None, f"missing {name}"


def test_shell_flat_chrome_covers_panels_keeps_workspace_opaque(
    qtbot: QtBot,
) -> None:
    """Production shell is flat: the sidebar host and AI dock still
    share one BackdropLayer wiring, but every chrome
    surface renders opaque (no capture, no blur), the decorative backdrop
    stays hidden, and the central workspace stays opaque."""
    engine, _, theme = _load_engine(qtbot)
    window = engine.rootObjects()[0]
    content = window.contentItem()

    backdrop = _find_quick_item(content, "f1BackgroundLayer")
    assert backdrop is not None
    assert abs(backdrop.width() - float(window.width())) < 1
    assert abs(backdrop.height() - float(window.height())) < 1
    # Flat shell: the decorative backdrop never renders (zero GPU cost).
    assert backdrop.property("visible") is False

    sidebar = _find_quick_item(content, "sidebarHost")
    rail_glass = _find_quick_item(content, "navRailGlass")
    dock = _find_quick_item(content, "agentDock")
    workspace = _find_quick_item(content, "workspaceHost")
    assert sidebar is not None and rail_glass is None
    assert dock is not None and workspace is not None

    # All chrome columns keep the same backdrop wiring (structural contract).
    assert sidebar.property("sourceItem").objectName() == "f1BackgroundLayer"
    assert dock.property("backdropSource").objectName() == "f1BackgroundLayer"
    # Flat contract: opaque panels, no real-time blur in any tier.
    assert sidebar.property("opaqueFallback") is True
    assert sidebar.property("blurEnabled") is False
    assert sidebar.property("fillColor").alpha() == 255

    # Central workspace stays opaque and untouched.
    assert workspace.property("color").alpha() == 255

    # Safe tier keeps the same flat opaque chrome without breaking layout.
    theme.setVisualQuality("safe")
    qtbot.waitUntil(lambda: sidebar.property("blurEnabled") is False)
    assert sidebar.property("fillColor").alpha() == 255


def test_shell_glass_integration_sidebar_toggle_stays_one_step(
    qtbot: QtBot,
) -> None:
    """Glass sidebar keeps the one-step width switch (ideal-UI spec 10.1:
    never animate the layout cell that resizes the WebEngine editor)."""
    engine, _, _ = _load_engine(qtbot)
    window = engine.rootObjects()[0]
    content = window.contentItem()
    sidebar = _find_quick_item(content, "sidebarHost")
    assert sidebar is not None

    toggle = window.findChild(object, "sidebarToggle")
    assert toggle is not None
    QMetaObject.invokeMethod(toggle, "clicked")
    qtbot.wait(40)
    assert abs(float(sidebar.property("width"))) < 1
    QMetaObject.invokeMethod(toggle, "clicked")
    qtbot.wait(40)
    assert float(sidebar.property("width")) > 100


def test_manuscript_host_is_flat_opaque_panel(qtbot: QtBot) -> None:
    """The central manuscript container is a flat opaque "paper" panel
    (clean modern design): same backdrop wiring, no capture, no blur, and
    Safe tier keeps the identical opaque rendering."""
    engine, _, theme = _load_engine(qtbot)
    window = engine.rootObjects()[0]
    content = window.contentItem()

    host = _find_quick_item(content, "manuscriptHost")
    assert host is not None
    assert host.property("sourceItem").objectName() == "f1BackgroundLayer"
    assert host.property("opaqueFallback") is True
    assert host.property("blurEnabled") is False
    assert host.property("fillColor").alpha() == 255

    theme.setVisualQuality("safe")
    qtbot.waitUntil(lambda: host.property("blurEnabled") is False)
    assert host.property("fillColor").alpha() == 255


def test_web_editor_theme_wiring_and_tokens(qtbot: QtBot) -> None:
    """The beige-editor root cause is fixed by wiring: NovelEditorView binds
    its canvas to Theme tokens and pushes them into the page on load/change.
    WebEngineView cannot instantiate offscreen, so this locks the wiring by
    source contract plus the token values themselves."""
    editor_qml = (
        Path(__file__).resolve().parent.parent.parent
        / "src"
        / "ai_novel_studio"
        / "ui_qml"
        / "qml"
        / "components"
        / "NovelEditorView.qml"
    ).read_text(encoding="utf-8")
    assert "property color editorSurfaceColor: Theme.tokens.color.bgEditor" in editor_qml
    assert "backgroundColor: editorSurfaceColor" in editor_qml
    assert "function applyCurrentTheme" in editor_qml
    assert "window.__novelEditor.applyTheme" in editor_qml
    assert "onTokensChanged" in editor_qml

    theme = ThemeProvider()
    assert theme.property("tokens")["color"]["bgEditor"] == "#FFFEFA"  # paper
    theme.setTheme("light")
    assert theme.property("tokens")["color"]["bgEditor"] == "#FFFFFF"
    theme.setTheme("dark")
    assert theme.property("tokens")["color"]["bgEditor"] == "#292A2D"


def test_typing_marks_editor_dirty_and_save_clears(qtbot: QtBot) -> None:
    facade = MockNovelStudioFacade(demo_mode=True)
    engine, facade, _ = _load_engine(qtbot, facade)
    window = engine.rootObjects()[0]
    editor = window.findChild(object, "manuscriptEditor")
    editor.setProperty("text", "模拟输入的正文内容")
    assert facade.property("editorState") == "DIRTY"
    facade.requestSave()
    assert facade.property("editorState") == "CLEAN"
    assert facade.property("currentRevision") == 4


def test_draft_button_opens_drawer_with_suggestion(qtbot: QtBot) -> None:
    facade = MockNovelStudioFacade(demo_mode=True)
    engine, facade, _ = _load_engine(qtbot, facade)
    facade.requestDraft()
    assert facade.property("aiDrawerOpen") is True
    suggestions = facade.property("suggestions")
    assert suggestions.rowCount() == 1


def test_chapter_selection_updates_editor_text(qtbot: QtBot) -> None:
    facade = MockNovelStudioFacade(demo_mode=True)
    engine, facade, _ = _load_engine(qtbot, facade)
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


def test_footer_settings_button_switches_page(qtbot: QtBot) -> None:
    engine, facade, _ = _load_engine(qtbot)
    window = engine.rootObjects()[0]
    settings_button = _find_quick_item(window.contentItem(), "nav-settings")
    assert settings_button is not None
    QMetaObject.invokeMethod(settings_button, "clicked")
    assert facade.property("activeNav") == "settings"


def test_navigation_writing_button_returns_to_writing(qtbot: QtBot) -> None:
    engine, facade, _ = _load_engine(qtbot)
    window = engine.rootObjects()[0]
    facade.setActiveNav("library")
    writing_button = _find_quick_item(window.contentItem(), "mode-writing")
    assert writing_button is not None
    QMetaObject.invokeMethod(writing_button, "clicked")
    assert facade.property("activeNav") == "writing"


def test_chapter_click_returns_to_writing(qtbot: QtBot) -> None:
    facade = MockNovelStudioFacade(demo_mode=True)
    engine, facade, _ = _load_engine(qtbot, facade)
    facade.setActiveNav("library")
    facade.selectChapter(3)
    assert facade.property("activeNav") == "writing"
    assert facade.property("currentChapterId") == "chapter-3"


def test_textarea_host_renders_creative_agent_panel(qtbot: QtBot) -> None:
    engine, facade, _ = _load_engine(qtbot)
    window = engine.rootObjects()[0]
    facade.toggleAiDrawer(True)
    panel = _find_visible_quick_item(window.contentItem(), "creativeAgentPanel")
    assert panel is not None
    assert window.findChild(object, "agentDock") is not None


def test_selection_quote_lays_out_preview_below_label_and_clear_button(
    qtbot: QtBot,
) -> None:
    facade = MockNovelStudioFacade(demo_mode=True)
    engine, facade, _ = _load_engine(qtbot, facade)
    """C1.4 regression: the selection chip must span the composer width.

    The chip previously had no implicitWidth (Rectangle default 0), so its
    inner RowLayout collapsed and the chapter label, preview and close button
    all stacked at x=0 and overlapped.
    """
    window = engine.rootObjects()[0]
    facade.toggleAiDrawer(True)

    selected_text = "清晨的雾港"
    source = str(facade.property("currentChapterBody"))
    facade.setSelectionReferenceJson(_selection_payload(source, selected_text))

    qtbot.waitUntil(
        lambda: (
            _find_visible_quick_item(window.contentItem(), "selectionReferenceChip") is not None
        ),
        timeout=5000,
    )
    qtbot.wait(300)  # let the 150ms fade-in settle
    chip = _find_visible_quick_item(window.contentItem(), "selectionReferenceChip")
    assert chip is not None
    assert chip.width() > 0, "chip collapsed to zero width"

    from PySide6.QtCore import QPointF

    label = _find_quick_item(chip, "selectionQuoteLabel")
    preview = _find_quick_item(chip, "selectionQuotePreview")
    close = _find_quick_item(chip, "clearSelectionButton")
    label_pos = label.mapToItem(chip, QPointF())
    preview_pos = preview.mapToItem(chip, QPointF())
    close_pos = close.mapToItem(chip, QPointF())
    assert selected_text in preview.property("text")
    assert label_pos.x() + label.width() <= close_pos.x() + 1
    assert label_pos.y() + label.height() <= preview_pos.y() + 1
    assert preview_pos.y() + preview.height() <= chip.height()
    assert preview_pos.x() + preview.width() <= chip.width()


def test_selection_chip_long_preview_stays_inside_chip(qtbot: QtBot) -> None:
    facade = MockNovelStudioFacade(demo_mode=True)
    engine, facade, _ = _load_engine(qtbot, facade)
    """A very long (cross-paragraph) quote preview must never overflow."""
    window = engine.rootObjects()[0]
    facade.toggleAiDrawer(True)

    source = str(facade.property("currentChapterBody"))
    facade.setSelectionReferenceJson(_selection_payload(source, source))

    qtbot.waitUntil(
        lambda: (
            _find_visible_quick_item(window.contentItem(), "selectionReferenceChip") is not None
        ),
        timeout=5000,
    )
    qtbot.wait(300)
    chip = _find_visible_quick_item(window.contentItem(), "selectionReferenceChip")
    assert chip is not None
    chip_right = chip.x() + chip.width()

    texts = []
    for child in chip.childItems():
        for leaf in child.childItems():
            value = leaf.property("text")
            if isinstance(value, str) and value:
                texts.append(leaf)
    for leaf in texts:
        assert leaf.x() + leaf.width() <= chip_right + 1, (
            f"text overflows chip right edge: {str(leaf.property('text'))[:12]}"
        )


def test_agent_dock_open_close_and_collapse(qtbot: QtBot) -> None:
    """AgentDock interactions are facade-driven and keep a visible expand tab."""
    engine = QQmlApplicationEngine()
    _ACTIVE_ENGINES.append(engine)
    engine.addImportPath(str(Path(app_qml_path()).parent))
    facade = MockNovelStudioFacade()
    theme = ThemeProvider()
    _register_frontend_context(engine, facade, theme)
    engine.loadData(
        QByteArray(
            b"""
            import QtQuick
            import QtQuick.Controls
            import QtQuick.Layouts
            import "components"
            ApplicationWindow {
                width: 1440
                height: 900
                visible: true
                RowLayout {
                    anchors.fill: parent
                    AgentDock {
                        open: Facade.aiDrawerOpen
                        windowWidth: 1440
                        Layout.fillHeight: true
                    }
                }
            }
            """
        ),
        QUrl.fromLocalFile(str(Path(app_qml_path()).parent / "dock-harness.qml")),
    )
    root = engine.rootObjects()[0]
    assert root is not None
    root.show()
    qtbot.waitUntil(lambda: root.width() > 0)
    dock = _find_quick_item(root.contentItem(), "agentDock")
    assert dock is not None

    assert dock.property("width") == 34
    tab = _find_quick_item(root.contentItem(), "agentExpandTab")
    assert tab is not None
    assert tab.property("visible") is True

    # Open through the facade (never by direct `root.open` assignment).
    facade.toggleAiDrawer(True)
    qtbot.waitUntil(lambda: dock.property("width") == dock.property("defaultWidth"))
    assert tab.property("visible") is False

    # Close through the panel header button; the expand tab must return.
    close_button = _find_quick_item(root.contentItem(), "agentCloseButton")
    assert close_button is not None
    QMetaObject.invokeMethod(close_button, "clicked")
    qtbot.waitUntil(lambda: facade.property("aiDrawerOpen") is False)
    qtbot.waitUntil(lambda: dock.property("width") == 34)
    assert tab.property("visible") is True

    # Reopen from the tab.
    QMetaObject.invokeMethod(dock, "openFromTab")
    qtbot.waitUntil(lambda: facade.property("aiDrawerOpen") is True)
    qtbot.waitUntil(lambda: dock.property("width") == dock.property("defaultWidth"))
    assert tab.property("visible") is False

    # Width restore respects the configured bounds.
    dock.setProperty("currentWidth", 10_000)
    qtbot.waitUntil(lambda: dock.property("width") == 648)
    dock.setProperty("currentWidth", 0)
    qtbot.waitUntil(lambda: dock.property("width") == dock.property("minWidth"))
    QMetaObject.invokeMethod(dock, "resetWidth")
    qtbot.waitUntil(lambda: dock.property("width") == dock.property("defaultWidth"))


def test_agent_dock_geometry_switches_in_one_step(qtbot: QtBot) -> None:
    """Ideal-UI 10.1: dock width snaps in every mode, content fades instead.

    C1.5 gated the width animation off only for WebEngine; the ideal-UI spec
    makes one-step geometry the rule for all modes so the editor never gets
    resized frame by frame.
    """
    engine = QQmlApplicationEngine()
    _ACTIVE_ENGINES.append(engine)
    engine.addImportPath(str(Path(app_qml_path()).parent))
    facade = MockNovelStudioFacade()
    theme = ThemeProvider()
    _register_frontend_context(engine, facade, theme)
    engine.loadData(
        QByteArray(
            b"""
            import QtQuick
            import QtQuick.Controls
            import QtQuick.Layouts
            import "components"
            ApplicationWindow {
                width: 1440
                height: 900
                visible: true
                RowLayout {
                    anchors.fill: parent
                    AgentDock {
                        open: Facade.aiDrawerOpen
                        windowWidth: 1440
                        Layout.fillHeight: true
                    }
                }
            }
            """
        ),
        QUrl.fromLocalFile(str(Path(app_qml_path()).parent / "dock-snap-harness.qml")),
    )
    root = engine.rootObjects()[0]
    assert root is not None
    root.show()
    qtbot.waitUntil(lambda: root.width() > 0)
    dock = _find_quick_item(root.contentItem(), "agentDock")
    assert dock is not None
    assert dock.property("width") == 34

    facade.toggleAiDrawer(True)
    # One event-loop pass: the width must already be the default 420.
    qtbot.wait(10)
    assert dock.property("width") == dock.property("defaultWidth")


def test_agent_dock_drag_previews_and_commits_on_release(qtbot: QtBot) -> None:
    """Ideal-UI 10.1: dragging shows a preview line and commits once."""
    engine = QQmlApplicationEngine()
    _ACTIVE_ENGINES.append(engine)
    engine.addImportPath(str(Path(app_qml_path()).parent))
    facade = MockNovelStudioFacade()
    theme = ThemeProvider()
    _register_frontend_context(engine, facade, theme)
    engine.loadData(
        QByteArray(
            b"""
            import QtQuick
            import QtQuick.Controls
            import QtQuick.Layouts
            import "components"
            ApplicationWindow {
                width: 1440
                height: 900
                visible: true
                RowLayout {
                    anchors.fill: parent
                    AgentDock {
                        open: Facade.aiDrawerOpen
                        windowWidth: 1440
                        Layout.fillHeight: true
                    }
                }
            }
            """
        ),
        QUrl.fromLocalFile(str(Path(app_qml_path()).parent / "dock-drag-harness.qml")),
    )
    root = engine.rootObjects()[0]
    assert root is not None
    root.show()
    qtbot.waitUntil(lambda: root.width() > 0)
    dock = _find_quick_item(root.contentItem(), "agentDock")
    preview = _find_quick_item(root.contentItem(), "agentDragPreview")
    assert dock is not None and preview is not None
    facade.toggleAiDrawer(True)
    qtbot.waitUntil(lambda: dock.property("width") == dock.property("defaultWidth"))

    # Simple click on the handle must not change the width.
    dock.setProperty("dragPointerX", 2.5)
    QMetaObject.invokeMethod(dock, "beginResizeDrag")
    QMetaObject.invokeMethod(dock, "commitResizeDrag")
    assert dock.property("dragging") is False
    assert dock.property("width") == dock.property("defaultWidth")

    # Real drag: the dock keeps its width while dragging; only a preview line
    # follows the pointer, and the width commits exactly once on release.
    dock.setProperty("dragPointerX", 2.5)
    QMetaObject.invokeMethod(dock, "beginResizeDrag")
    qtbot.waitUntil(lambda: dock.property("dragging") is True)
    qtbot.waitUntil(lambda: preview.property("visible") is True)

    dock.setProperty("dragPointerX", -80.0)
    QMetaObject.invokeMethod(dock, "updateResizeDrag")
    qtbot.waitUntil(lambda: dock.property("dragPreviewX") == 0.0)
    assert dock.property("width") == dock.property("defaultWidth"), (
        "dock must not resize while dragging"
    )

    QMetaObject.invokeMethod(dock, "commitResizeDrag")
    assert dock.property("dragging") is False
    qtbot.waitUntil(lambda: dock.property("width") == dock.property("defaultWidth") + 80)
    qtbot.waitUntil(lambda: preview.property("visible") is False)

    # Release inside the bounds: width derives from the pointer position.
    QMetaObject.invokeMethod(dock, "resetWidth")
    qtbot.waitUntil(lambda: dock.property("width") == dock.property("defaultWidth"))
    dock.setProperty("dragPointerX", 2.5)
    QMetaObject.invokeMethod(dock, "beginResizeDrag")
    dock.setProperty("dragPointerX", 60.0)
    QMetaObject.invokeMethod(dock, "updateResizeDrag")
    QMetaObject.invokeMethod(dock, "commitResizeDrag")
    qtbot.waitUntil(
        lambda: (
            dock.property("width")
            == max(dock.property("minWidth"), dock.property("defaultWidth") - 60)
        ),
        timeout=5000,
    )


def test_timeline_cards_stay_within_content_width(qtbot: QtBot) -> None:
    """C1.2: every Agent card right edge stays inside the timeline content area.

    Runs at the dock widths covered by the acceptance matrix (360/420/520),
    plus a very narrow width to prove the delegate-width rule is not
    accidentally bypassed with a fixed fallback.
    """
    engine = QQmlApplicationEngine()
    _ACTIVE_ENGINES.append(engine)
    engine.addImportPath(str(Path(app_qml_path()).parent))
    facade = MockNovelStudioFacade()
    theme = ThemeProvider()
    _register_frontend_context(engine, facade, theme)

    timeline_model = facade.property("agentTimeline")
    for kind in (
        "user_text",
        "tool_call",
        "text_diff",
        "confirmation",
        "form_card",
        "change_set",
    ):
        timeline_model.append_item(
            AgentTimelineItemDto(
                id=f"seed-{kind}",
                kind=kind,
                text=(
                    "这是一段非常长的示例文本，用来验证卡片在窄面板下不会把右侧内容裁掉，"
                    "并且会通过 WordWrap 换行而不是横向溢出。"
                ),
                label="修改对比 · 较长标题",
                current_text="当前文本：" + "很长的当前内容，" * 8,
                draft_text="修改文本：" + "很长的修改内容，" * 8,
                field_labels=("人物名", "关系", "备注"),
                field_values=("林默", "旧友", "待确认"),
                target="人物 · 林默",
                operation="更新",
                before_text="码头工人" + "很长的旧值，" * 6,
                after_text="退役水手" + "很长的新值，" * 6,
                risk="高",
                reason="Mock 提案：" + "来源理由，" * 10,
            )
        )

    engine.loadData(
        QByteArray(
            b"""
            import QtQuick
            import QtQuick.Controls
            import QtQuick.Layouts
            import "components"
            ApplicationWindow {
                width: 700
                height: 900
                visible: true
                Rectangle {
                    id: host
                    anchors.fill: parent
                    color: "#202124"
            CreativeAgentPanel {
                anchors.fill: parent
            }
                }
            }
            """
        ),
        QUrl.fromLocalFile(str(Path(app_qml_path()).parent / "panel-harness.qml")),
    )
    root = engine.rootObjects()[0]
    assert root is not None
    root.show()
    qtbot.waitUntil(lambda: root.width() > 0)
    content = root.contentItem()

    for panel_width in (360, 420, 520, 300):
        root.resize(panel_width, 900)
        qtbot.waitUntil(
            lambda width=panel_width: root.width() == width,
            timeout=5000,
        )
        panel = _find_quick_item(content, "creativeAgentPanel")
        timeline = _find_quick_item(content, "agentTimeline")
        assert panel is not None and timeline is not None

        # Timeline content right edge = panel right edge minus panel margins.
        panel_right = panel.x() + panel.width()
        timeline_right = timeline.x() + timeline.width()
        available_right = panel_right - 12
        assert timeline_right <= available_right + 1

        card_names = (
            "agentTextBlock",  # user_text
            "toolCallCard",  # tool_call
            "textDiffCard",  # text_diff
            "confirmationCard",  # confirmation
            "formCard",  # form_card
            "changeSetCard",  # change_set
        )
        for index, card_name in enumerate(card_names):
            # ListView virtualizes delegates; bring each one into view first.
            timeline.setProperty("currentIndex", index)
            qtbot.waitUntil(
                lambda name=card_name: _find_quick_item(content, name) is not None,
                timeout=5000,
            )
            card = _find_quick_item(content, card_name)
            assert card is not None, f"{card_name} missing at {panel_width}px"
            card_right = card.x() + card.width()
            assert card_right <= timeline_right + 1, (
                f"{card_name} right edge {card_right} exceeds timeline "
                f"{timeline_right} at panel width {panel_width}"
            )


def test_sidebar_search_filters_chapter_list(qtbot: QtBot) -> None:
    facade = MockNovelStudioFacade(demo_mode=True)
    engine, facade, _ = _load_engine(qtbot, facade)
    window = engine.rootObjects()[0]
    search = window.findChild(object, "sidebarSearch")
    assert search is not None
    search.setProperty("text", "灯塔")
    model = facade.property("chapters")
    assert model.rowCount() == 2
    search.setProperty("text", "")
    assert model.rowCount() == 7


def test_theme_cycles_via_provider_and_more_menu(qtbot: QtBot) -> None:
    engine, _, theme = _load_engine(qtbot)
    window = engine.rootObjects()[0]
    more_button = window.findChild(object, "statusMoreButton")
    assert more_button is not None
    assert theme.property("themeName") == "paper"
    theme.setTheme(theme.nextThemeName())
    assert theme.property("themeName") == "light"
    theme.setTheme(theme.nextThemeName())
    assert theme.property("themeName") == "dark"


def test_draft_button_opens_drawer(qtbot: QtBot) -> None:
    facade = MockNovelStudioFacade(demo_mode=True)
    engine, facade, _ = _load_engine(qtbot, facade)
    facade.requestDraft()

    assert facade.property("aiDrawerOpen") is True
    assert facade.property("suggestions").rowCount() == 1


def test_drawer_close_button_closes_drawer(qtbot: QtBot) -> None:
    facade = MockNovelStudioFacade(demo_mode=True)
    engine, facade, _ = _load_engine(qtbot, facade)
    window = engine.rootObjects()[0]
    facade.requestDraft()
    assert facade.property("aiDrawerOpen") is True
    dock = window.findChild(object, "agentDock")
    assert dock is not None
    qtbot.waitUntil(lambda: dock.property("width") == dock.property("defaultWidth"))
    close_button = window.findChild(object, "agentCloseButton")
    assert close_button is not None
    QMetaObject.invokeMethod(close_button, "clicked")
    assert facade.property("aiDrawerOpen") is False
    qtbot.waitUntil(lambda: dock.property("width") == 34)


def test_project_controls_exist_in_sidebar(qtbot: QtBot) -> None:
    engine, _, _ = _load_engine(qtbot)
    window = engine.rootObjects()[0]
    for name in (
        "openProjectButton",
        "newProjectButton",
        "newProjectDialog",
        "projectOpenDialog",
        "projectMessage",
        "newVolumeButton",
        "newChapterButton",
        "importManuscriptButton",
        "deleteEmptyChaptersButton",
        "newVolumeDialog",
        "newChapterDialog",
        "manuscriptImportDialog",
        "deleteEmptyChaptersDialog",
    ):
        assert window.findChild(object, name) is not None, f"missing {name}"
    assert window.findChild(object, "resetDemoButton") is None


def test_agent_panel_separates_chat_from_draft_generation() -> None:
    panel = (Path(app_qml_path()).parent / "components" / "CreativeAgentPanel.qml").read_text(
        encoding="utf-8"
    )
    assert "Facade.startAssistantChat(text)" in panel
    assert "Facade.startAgentTurn(command)" in panel
    assert 'Facade.startAgentTurn("生成章节草稿")' in panel
    assert "Facade.requestDraft()" not in panel


def test_real_project_loads_into_editor(qtbot: QtBot, tmp_path: Path) -> None:
    if not BACKEND_AVAILABLE:
        import pytest

        pytest.skip("needs backend")
    root = _create_temp_project(tmp_path / "novel")
    engine, facade, _ = _load_engine(qtbot)
    window = engine.rootObjects()[0]
    editor = window.findChild(object, "manuscriptEditor")

    error = facade.openProject(str(root))

    assert error == ""
    assert "这是测试正文" in editor.property("text")
    assert facade.property("projectSource") == "project"


def test_close_project_returns_to_empty_editor(qtbot: QtBot, tmp_path: Path) -> None:
    if not BACKEND_AVAILABLE:
        import pytest

        pytest.skip("needs backend")
    root = _create_temp_project(tmp_path / "novel")
    engine, facade, _ = _load_engine(qtbot)
    window = engine.rootObjects()[0]
    editor = window.findChild(object, "manuscriptEditor")
    facade.openProject(str(root))
    assert facade.property("projectSource") == "project"

    facade.closeProject()

    assert facade.property("projectSource") == "empty"
    assert editor.property("text") == ""
    assert facade.property("modelStatusText") == "未配置"
    model_chip = window.findChild(object, "modelStatusChip")
    assert model_chip is not None
    assert model_chip.property("value") != "Mock"


def test_save_conflict_shows_reload_button_and_recovers(qtbot: QtBot, tmp_path: Path) -> None:
    if not BACKEND_AVAILABLE:
        import pytest

        pytest.skip("needs backend")
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
    save_item = window.findChild(object, "chapterSaveButton")
    reload_item = window.findChild(object, "chapterReloadButton")
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

    QMetaObject.invokeMethod(save_item, "clicked")
    assert facade.property("editorState") == "CONFLICT"
    assert reload_item.property("enabled") is True

    QMetaObject.invokeMethod(reload_item, "clicked")
    assert facade.property("editorState") == "CLEAN"
    assert "外部写入的正文" in editor.property("text")
    assert facade.property("currentRevision") == 2


def test_chapter_generation_menu_is_removed_from_production_shell(qtbot: QtBot) -> None:
    engine, facade, theme = _load_engine(qtbot)
    window = engine.rootObjects()[0]
    assert window.findChild(object, "chapterMenuButton") is None
    assert window.findChild(object, "generationConfigDialog") is None
    assert window.findChild(object, "chapterSaveButton") is not None


def test_usage_values_update_after_generation(qtbot: QtBot, tmp_path: Path) -> None:
    root = _create_temp_project(tmp_path / "novel")
    port = FakeDraftPort(draft_text="草稿正文")
    facade = MockNovelStudioFacade(draft_port=port)
    facade.openProject(str(root))
    engine, facade, _ = _load_engine(qtbot, facade)
    window = engine.rootObjects()[0]

    assert facade.property("usageInputOutputText") == "0 / 0"
    assert window.findChild(object, "statusMoreMenu") is not None

    facade.requestDraft()
    qtbot.waitUntil(
        lambda: facade.property("draftStatus") == "COMPLETED",
        timeout=5000,
    )

    assert facade.property("usageInputOutputText") == "1.2K / 800"
    assert facade.property("usageCostText") == "¥0.018"
    assert facade.property("usageCacheText") == "缓存 600"
    assert facade.property("usageCallsText") == "1 次调用"


def test_overview_pages_exist_and_show_counts(qtbot: QtBot, tmp_path: Path) -> None:
    if not BACKEND_AVAILABLE:
        import pytest

        pytest.skip("needs backend")
    root = _create_temp_project(tmp_path / "novel")
    facade = MockNovelStudioFacade()
    facade.openProject(str(root))
    engine, facade, _ = _load_engine(qtbot, facade)
    window = engine.rootObjects()[0]

    for page in ("charactersPage", "memoryPage", "auditPage"):
        assert window.findChild(object, page) is not None, f"missing {page}"

    facade.setActiveNav("characters")
    assert facade.property("activeNav") == "library"
    characters_page = window.findChild(object, "charactersPage")
    assert characters_page.property("visible") is True
    count_chip = window.findChild(object, "charactersPageCount")
    assert count_chip is not None
    assert count_chip.property("value") == "0 人"


def test_readonly_lists_exist_and_show_empty_state(qtbot: QtBot, tmp_path: Path) -> None:
    if not BACKEND_AVAILABLE:
        import pytest

        pytest.skip("needs backend")
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


def test_character_detail_panel_shows_after_selection(qtbot: QtBot, tmp_path: Path) -> None:
    if not BACKEND_AVAILABLE:
        import pytest

        pytest.skip("needs backend")
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
    assert facade.property("activeNav") == "library"
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


def test_audit_evidence_reveal_selects_text_in_editor(qtbot: QtBot, tmp_path: Path) -> None:
    if not BACKEND_AVAILABLE:
        import pytest

        pytest.skip("needs backend")
    from .test_readonly_views import create_project_with_audit

    root = create_project_with_audit(tmp_path)
    facade = MockNovelStudioFacade()
    facade.openProject(str(root))
    facade.setActiveNav("audit")
    engine, facade, _ = _load_engine(qtbot, facade)
    window = engine.rootObjects()[0]
    editor = window.findChild(object, "manuscriptEditor")

    facade.revealAuditEvidence(0)

    assert facade.property("activeNav") == "writing"
    qtbot.waitUntil(
        lambda: editor.property("selectedText") == "第二段。",
        timeout=5000,
    )


def test_memory_detail_panel_shows_after_selection(qtbot: QtBot, tmp_path: Path) -> None:
    if not BACKEND_AVAILABLE:
        import pytest

        pytest.skip("needs backend")
    from .test_readonly_views import create_project_with_memory

    root = create_project_with_memory(tmp_path)
    facade = MockNovelStudioFacade()
    facade.openProject(str(root))
    facade.selectChapter(2)
    engine, facade, _ = _load_engine(qtbot, facade)
    window = engine.rootObjects()[0]
    detail = window.findChild(object, "memoryDetail")
    assert detail is not None

    facade.setActiveNav("memory")
    memory_tabs = window.findChild(object, "memoryLibraryTabs")
    assert memory_tabs is not None
    memory_tabs.setProperty("currentIndex", 1)
    facade.selectMemory(0)

    assert facade.property("memoryDetailVisible") is True
    qtbot.waitUntil(lambda: detail.property("visible") is True, timeout=5000)
    assert "灯塔" in facade.property("memoryDetailContent")

    close_button = window.findChild(object, "closeMemoryDetailButton")
    assert close_button is not None
    from PySide6.QtCore import QMetaObject

    QMetaObject.invokeMethod(close_button, "clicked")
    assert facade.property("memoryDetailVisible") is False


def test_audit_ignore_button_updates_finding_status(qtbot: QtBot, tmp_path: Path) -> None:
    if not BACKEND_AVAILABLE:
        import pytest

        pytest.skip("needs backend")
    from .test_readonly_views import create_project_with_audit

    root = create_project_with_audit(tmp_path)
    facade = MockNovelStudioFacade()
    facade.openProject(str(root))
    facade.setActiveNav("audit")
    engine, facade, _ = _load_engine(qtbot, facade)
    window = engine.rootObjects()[0]
    ignore_button = _find_quick_item(window.contentItem(), "ignoreAuditButton")
    assert ignore_button is not None

    QMetaObject.invokeMethod(ignore_button, "clicked")

    audits = facade.property("auditViews")
    qtbot.waitUntil(
        lambda: audits.data(audits.index(0), audits.ROLE_STATUS) == "REJECTED",
        timeout=5000,
    )
    assert "已更新" in facade.property("saveStatusText")
