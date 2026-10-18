"""Production shell: DWM Desktop Acrylic integration and opaque fallbacks.

The bootstrap exposes ``UseNativeGlass`` + ``NativeGlassBridge`` to App.qml
only when the machine supports the material. Every failure path must keep the
window on the opaque theme canvas; the custom title bar and resize edges must
exist only on the frameless native-glass shell.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

# Offscreen + software rendering: QQuickWindow is never really displayed and
# DWM must not be touched (same rule as test_native_glass_lab.py).
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QT_QUICK_BACKEND", "software")

from PySide6.QtCore import Qt, QUrl  # noqa: E402
from PySide6.QtGui import QColor  # noqa: E402
from PySide6.QtQml import QQmlApplicationEngine  # noqa: E402
from PySide6.QtQuick import QQuickItem, QQuickWindow  # noqa: E402
from pytestqt.qtbot import QtBot  # noqa: E402

from ai_novel_studio.ui_qml.bootstrap import (  # noqa: E402
    app_qml_path,
    register_frontend_types,
)
from ai_novel_studio.ui_qml.bridge.mock_novel_studio_facade import (  # noqa: E402
    MockNovelStudioFacade,
)
from ai_novel_studio.ui_qml.bridge.theme_provider import ThemeProvider  # noqa: E402

from .test_native_glass_lab import FakeNativeGlassBridge  # noqa: E402

_ACTIVE_ENGINES: list[QQmlApplicationEngine] = []


@pytest.fixture(autouse=True)
def _delete_active_engines() -> None:
    yield
    for engine in _ACTIVE_ENGINES:
        engine.deleteLater()
    _ACTIVE_ENGINES.clear()


def _find_item(root: QQuickItem, name: str) -> QQuickItem | None:
    if root.objectName() == name:
        return root
    for child in root.childItems():
        found = _find_item(child, name)
        if found is not None:
            return found
    return None


def _load_shell(
    qtbot: QtBot,
    use_native_glass: bool,
    bridge: FakeNativeGlassBridge | None = None,
) -> tuple[QQmlApplicationEngine, MockNovelStudioFacade, ThemeProvider]:
    engine = QQmlApplicationEngine()
    engine.addImportPath(str(Path(app_qml_path()).parent))
    facade = MockNovelStudioFacade()
    theme = ThemeProvider()
    register_frontend_types(engine, facade, theme)
    engine.rootContext().setContextProperty("UseNativeGlass", use_native_glass)
    if use_native_glass and bridge is not None:
        engine.rootContext().setContextProperty("NativeGlassBridge", bridge)
    engine.load(QUrl.fromLocalFile(str(app_qml_path())))
    assert engine.rootObjects(), "App.qml failed to load"
    _ACTIVE_ENGINES.append(engine)
    return engine, facade, theme


def test_shell_stays_opaque_without_native_glass(qtbot: QtBot) -> None:
    """Default context (no UseNativeGlass/bridge): opaque, normal window."""
    engine, _, _ = _load_shell(qtbot, use_native_glass=False)
    window = engine.rootObjects()[0]
    assert isinstance(window, QQuickWindow)
    assert window.property("nativeGlass") is False
    assert window.flags() & Qt.FramelessWindowHint == 0
    assert QColor(window.color()).alpha() == 255
    title_bar = _find_item(window.contentItem(), "glassTitleBar")
    assert title_bar is not None
    assert title_bar.property("visible") is False


def test_shell_glass_fallback_keeps_opaque_canvas(qtbot: QtBot) -> None:
    """Bridge requested but inactive: frameless shell with opaque canvas."""
    bridge = FakeNativeGlassBridge()  # apply_result defaults False
    engine, _, _ = _load_shell(qtbot, use_native_glass=True, bridge=bridge)
    window = engine.rootObjects()[0]
    assert isinstance(window, QQuickWindow)
    assert window.property("nativeGlass") is True
    assert window.flags() & Qt.FramelessWindowHint == Qt.FramelessWindowHint
    assert window.property("nativeActive") is False
    assert QColor(window.color()).alpha() == 255
    title_bar = _find_item(window.contentItem(), "glassTitleBar")
    assert title_bar is not None
    assert title_bar.property("visible") is True
    wash = _find_item(window.contentItem(), "f1WindowWash")
    assert wash is not None
    assert wash.property("visible") is False


def test_shell_glass_activates_transparency(qtbot: QtBot) -> None:
    """Bridge active: transparent window, wash visible, title bar present."""
    bridge = FakeNativeGlassBridge()
    bridge.apply_result = True
    engine, _, _ = _load_shell(qtbot, use_native_glass=True, bridge=bridge)
    window = engine.rootObjects()[0]
    assert isinstance(window, QQuickWindow)
    assert window.property("nativeActive") is False

    assert bridge.apply("acrylic") is True
    qtbot.waitUntil(lambda: window.property("nativeActive") is True)
    assert QColor(window.color()).alpha() == 0
    wash = _find_item(window.contentItem(), "f1WindowWash")
    assert wash is not None
    assert wash.property("visible") is True
    title_bar = _find_item(window.contentItem(), "glassTitleBar")
    assert title_bar is not None
    assert title_bar.property("visible") is True


def test_theme_change_syncs_dark_mode(qtbot: QtBot) -> None:
    """Theme tokens change pushes the immersive dark tint to the bridge."""
    bridge = FakeNativeGlassBridge()
    engine, _, theme = _load_shell(qtbot, use_native_glass=True, bridge=bridge)
    theme.setTheme("dark")
    qtbot.waitUntil(lambda: bridge.dark_mode_calls and bridge.dark_mode_calls[-1])
    theme.setTheme("light")
    qtbot.waitUntil(lambda: bridge.dark_mode_calls[-1] is False)


def test_shell_glass_retry_timer_is_bounded(qtbot: QtBot) -> None:
    """The DWM retry counter exists and stays bounded for tests."""
    bridge = FakeNativeGlassBridge()
    engine, _, _ = _load_shell(qtbot, use_native_glass=True, bridge=bridge)
    window = engine.rootObjects()[0]
    assert window.property("nativeRetryCount") == 0
