import pytest
from PySide6.QtCore import QCoreApplication, QEvent, QMetaObject, QObject, QPointF, Qt, QUrl
from PySide6.QtQml import QQmlApplicationEngine
from PySide6.QtQuick import QQuickWindow
from PySide6.QtTest import QTest

from ai_novel_studio.application.codex_controls_service import (
    CodexControlSnapshot,
    CodexControlsService,
    CodexModelChoice,
)
from ai_novel_studio.infrastructure.codex.preferences import CodexPreferences, CodexPreferencesStore
from ai_novel_studio.ui_qml.bootstrap import app_qml_path, register_frontend_types
from ai_novel_studio.ui_qml.bridge.codex_controls_bridge import CodexControlsBridge
from ai_novel_studio.ui_qml.bridge.codex_session_bridge import CodexSessionController
from ai_novel_studio.ui_qml.bridge.mock_novel_studio_facade import MockNovelStudioFacade

from .test_outline_page import _find


@pytest.fixture
def picker(qtbot, tmp_path):
    store = CodexPreferencesStore(tmp_path / "settings.json")
    service = CodexControlsService(store, tmp_path)
    service.snapshot = CodexControlSnapshot(
        (
            CodexModelChoice("model-one", "模型一", ("low", "high"), "high", True),
            CodexModelChoice("model-two", "模型二", ("low", "vendor-effort"), "low", False),
        ),
        CodexPreferences("model-one", "high", False),
        "ChatGPT 已登录",
        "短时剩余 80%",
        None,
    )
    controller = CodexSessionController(session_factory=lambda _: None)
    facade = MockNovelStudioFacade(codex_controller=controller)
    facade.toggleAiDrawer(True)
    facade.setReduceMotion(True)
    engine = QQmlApplicationEngine()
    _, theme = register_frontend_types(engine, facade)
    controls = CodexControlsBridge(engine, service=service)
    controls._apply(service.snapshot)
    engine.rootContext().setContextProperty("CodexSettings", controls)
    warnings = []
    engine.warnings.connect(lambda values: warnings.extend(v.toString() for v in values))
    engine.load(QUrl.fromLocalFile(str(app_qml_path())))
    assert engine.rootObjects(), warnings
    window = engine.rootObjects()[0]
    assert isinstance(window, QQuickWindow)
    qtbot.wait(80)
    yield window, store, warnings
    controller.close()
    engine.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)


def _click(window, item):
    assert item is not None and item.isVisible()
    QTest.mouseClick(
        window,
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
        item.mapToScene(item.boundingRect().center()).toPoint(),
    )


def test_compact_picker_selects_real_model_and_supported_effort_without_expanding_settings(
    picker, qtbot
):
    window, store, warnings = picker
    panel = _find(window.contentItem(), "creativeAgentPanel")
    assert not panel.property("controlsExpanded")
    model = _find(window.contentItem(), "composerCodexModelCombo")
    _click(window, model)
    qtbot.waitUntil(
        lambda: _find(window.contentItem(), "composerCodexModelCombo-choice-1") is not None
    )
    assert _find(window.contentItem(), "composerCodexModelCombo-selected-0").isVisible()
    _click(window, _find(window.contentItem(), "composerCodexModelCombo-choice-1"))
    assert store.load().model == "model-two"
    assert store.load().effort == "low"
    _click(window, model)
    qtbot.waitUntil(lambda: _find(window.contentItem(), "composerCodexEffortChoice-1") is not None)
    _click(window, _find(window.contentItem(), "composerCodexEffortChoice-1"))
    assert store.load().effort == "vendor-effort"
    assert not panel.property("controlsExpanded")
    assert not warnings


def test_model_and_effort_share_one_selector_inside_the_composer(picker):
    window, _, _ = picker
    model = _find(window.contentItem(), "composerCodexModelCombo")
    box = _find(window.contentItem(), "agentComposerBox")
    assert box is not None
    position = model.mapToItem(box, QPointF(0, 0))
    assert position.x() >= 0 and position.y() >= 0
    assert position.x() + model.width() <= box.width()
    assert position.y() + model.height() <= box.height()
    effort = _find(window.contentItem(), "composerCodexEffortLabel")
    assert effort is not None and effort.isVisible() and effort.property("text") == "High"
    assert _find(window.contentItem(), "composerCodexEffortCombo") is None


def test_slash_model_opens_the_compact_picker_instead_of_the_large_settings_panel(picker, qtbot):
    window, _, warnings = picker
    _find(window.contentItem(), "agentComposerInput").setProperty("text", "/model")
    assert QMetaObject.invokeMethod(_find(window.contentItem(), "agentComposer"), "submit")
    qtbot.waitUntil(
        lambda: _find(window.contentItem(), "composerCodexModelCombo-choice-0") is not None
    )
    assert not _find(window.contentItem(), "creativeAgentPanel").property("controlsExpanded")
    QTest.keyClick(window, Qt.Key.Key_Escape)
    popup = window.findChild(QObject, "composerCodexModelComboPopup")
    qtbot.waitUntil(lambda: not popup.property("visible"))
    assert not warnings


def test_compact_model_menu_supports_arrow_keys_and_enter(picker, qtbot):
    window, store, warnings = picker
    model = _find(window.contentItem(), "composerCodexModelCombo")
    _click(window, model)
    qtbot.waitUntil(
        lambda: _find(window.contentItem(), "composerCodexModelCombo-choice-1") is not None
    )
    QTest.keyClick(window, Qt.Key.Key_Down)
    QTest.keyClick(window, Qt.Key.Key_Return)
    assert store.load().model == "model-two"
    assert not warnings


def test_session_panel_still_toggles_network_and_collapses_without_hiding_model_picker(
    picker, qtbot
):
    window, store, warnings = picker
    panel = _find(window.contentItem(), "creativeAgentPanel")
    button = _find(panel, "assistantControlsButton")
    _click(window, button)
    qtbot.waitUntil(lambda: panel.property("controlsExpanded"))
    qtbot.wait(60)
    network = _find(panel, "codexWebSearchCheck")
    _click(window, network)
    assert store.load().web_search is True
    _click(window, button)
    assert not panel.property("controlsExpanded")
    assert _find(panel, "composerCodexModelCombo").isVisible()
    assert not warnings
