from pathlib import Path

from PySide6.QtCore import Q_ARG, QMetaObject, QUrl
from PySide6.QtQml import QQmlComponent, QQmlEngine
from PySide6.QtQuick import QQuickItem
from shiboken6 import delete

from ai_novel_studio.application.codex_controls_service import (
    CodexControlSnapshot,
    CodexControlsService,
    CodexModelChoice,
)
from ai_novel_studio.infrastructure.codex.app_server import CodexConnectionError
from ai_novel_studio.infrastructure.codex.preferences import CodexPreferences, CodexPreferencesStore
from ai_novel_studio.ui_qml.bootstrap import app_qml_path
from ai_novel_studio.ui_qml.bridge.codex_controls_bridge import CodexControlsBridge, _Refresh
from ai_novel_studio.ui_qml.bridge.codex_session_bridge import CodexSessionController
from ai_novel_studio.ui_qml.bridge.mock_novel_studio_facade import MockNovelStudioFacade
from ai_novel_studio.ui_qml.bridge.theme_provider import ThemeProvider


def test_qml_model_effort_and_network_controls_save_the_real_choice(qtbot, tmp_path: Path):
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
    engine = QQmlEngine()
    controls = CodexControlsBridge(engine, service=service)
    controls._apply(service.snapshot)
    facade = MockNovelStudioFacade(codex_controller=CodexSessionController())
    theme = ThemeProvider()
    engine.rootContext().setContextProperty("Facade", facade)
    engine.rootContext().setContextProperty("Theme", theme)
    engine.rootContext().setContextProperty("CodexSettings", controls)
    component = QQmlComponent(
        engine,
        QUrl.fromLocalFile(
            str(
                Path(app_qml_path()).parent / "components" / "CodexControls.qml",
            )
        ),
    )
    root = component.create()
    assert root is not None, component.errors()
    model = root.findChild(QQuickItem, "codexModelCombo")
    effort = root.findChild(QQuickItem, "codexEffortCombo")
    network = root.findChild(QQuickItem, "codexWebSearchCheck")
    assert model.property("count") == 2
    assert effort.property("currentValue") == "high"
    model.setProperty("currentIndex", 1)
    assert QMetaObject.invokeMethod(model, "activated", Q_ARG(int, 1))
    assert store.load().model == "model-two"
    assert effort.property("currentValue") == "low"
    effort.setProperty("currentIndex", 1)
    assert QMetaObject.invokeMethod(effort, "activated", Q_ARG(int, 1))
    assert store.load().effort == "vendor-effort"
    network.setProperty("checked", True)
    assert QMetaObject.invokeMethod(network, "clicked")
    assert store.load().web_search is True
    root.deleteLater()
    engine.deleteLater()


def test_catalog_failure_keeps_specific_safe_connection_error(qtbot, tmp_path):
    service = CodexControlsService(CodexPreferencesStore(tmp_path / "settings.json"), tmp_path)

    def fail():
        raise CodexConnectionError("没有找到 Codex，请检查安装及 PATH")

    service.refresh = fail
    bridge = CodexControlsBridge(service=service)
    _Refresh(bridge).run()
    assert "没有找到 Codex" in bridge.statusText
    assert not bridge.ready


def test_catalog_unknown_errors_never_show_raw_payload(qtbot, tmp_path):
    service = CodexControlsService(CodexPreferencesStore(tmp_path / "settings.json"), tmp_path)

    def fail():
        raise RuntimeError("secret-provider-payload")

    service.refresh = fail
    bridge = CodexControlsBridge(service=service)
    _Refresh(bridge).run()
    assert "secret-provider-payload" not in bridge.statusText


def test_catalog_completion_after_window_destruction_does_not_emit(qtbot, tmp_path):
    service = CodexControlsService(CodexPreferencesStore(tmp_path / "settings.json"), tmp_path)
    bridge = CodexControlsBridge(service=service)

    def complete_after_close():
        delete(bridge)
        return None

    service.refresh = complete_after_close
    _Refresh(bridge).run()
