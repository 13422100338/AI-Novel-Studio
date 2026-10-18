"""Native Glass Lab: DWM bridge state machine, fallbacks and layout sanity.

The lab is the isolated experiment page for the native Desktop Acrylic / Mica
direction (AI-Novel-Studio isolation ticket: 原生毛玻璃测试界面). DWM calls are
replaced by ``FakeNativeGlassBridge`` so offscreen runs never touch
SetWindowCompositionAttribute; every failure path must keep the window on the
opaque theme fallback.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

# Offscreen + software rendering: QQuickWindow is never really displayed and
# DWM must not be touched (same rule as scripts/capture_native_glass_lab.py).
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QT_QUICK_BACKEND", "software")

from PySide6.QtCore import (  # noqa: E402
    Property,
    QMetaObject,
    QObject,
    QPointF,
    QRectF,
    QUrl,
    Signal,
    Slot,
)
from PySide6.QtGui import QColor  # noqa: E402
from PySide6.QtQml import QQmlApplicationEngine  # noqa: E402
from PySide6.QtQuick import QQuickItem, QQuickWindow  # noqa: E402
from pytestqt.qtbot import QtBot  # noqa: E402

from ai_novel_studio.ui_qml.bootstrap import (  # noqa: E402
    native_glass_lab_qml_path,
    register_frontend_types,
)
from ai_novel_studio.ui_qml.bridge.mock_novel_studio_facade import (  # noqa: E402
    MockNovelStudioFacade,
)
from ai_novel_studio.ui_qml.bridge.theme_provider import ThemeProvider  # noqa: E402

_ACTIVE_ENGINES: list[QQmlApplicationEngine] = []


class FakeNativeGlassBridge(QObject):
    """Scriptable stand-in for ``NativeGlassBridge``.

    Mirrors the real bridge surface: ``platformName`` / ``buildText`` /
    ``nativeSupported`` / ``transparencyEffects`` / ``unsupportedReason`` /
    ``activeKind`` / ``nativeActive`` properties plus the ``apply`` /
    ``setDarkMode`` / ``refresh`` slots. ``apply()`` records every call and
    returns ``apply_result`` for non-"none" kinds (default False, so the lab
    stays on its opaque fallback).
    """

    capabilitiesChanged = Signal()

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self.apply_result = False
        self.calls: list[str] = []
        self.dark_mode_calls: list[bool] = []
        self.refresh_calls = 0
        self._active_kind = "none"

    @Property(str, constant=True)
    def platformName(self) -> str:
        return "offscreen-fake"

    @Property(str, constant=True)
    def buildText(self) -> str:
        return "-"

    @Property(bool, constant=True)
    def nativeSupported(self) -> bool:
        return True

    @Property(bool, constant=True)
    def transparencyEffects(self) -> bool:
        return False

    @Property(str, constant=True)
    def unsupportedReason(self) -> str:
        return "offscreen fake bridge"

    @Property(str, notify=capabilitiesChanged)
    def activeKind(self) -> str:
        return self._active_kind

    @Property(bool, notify=capabilitiesChanged)
    def nativeActive(self) -> bool:
        return self._active_kind != "none"

    @Slot(str, result=bool)
    def apply(self, kind: str) -> bool:
        self.calls.append(kind)
        if kind == "none":
            self._active_kind = "none"
            self.capabilitiesChanged.emit()
            return False
        self._active_kind = kind if self.apply_result else "none"
        self.capabilitiesChanged.emit()
        return self.apply_result

    @Slot(bool, result=bool)
    def setDarkMode(self, enabled: bool) -> bool:
        self.dark_mode_calls.append(enabled)
        return True

    @Slot(result=bool)
    def refresh(self) -> bool:
        self.refresh_calls += 1
        return False


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


def _load_lab(
    qtbot: QtBot,
) -> tuple[
    QQmlApplicationEngine,
    MockNovelStudioFacade,
    ThemeProvider,
    FakeNativeGlassBridge,
    QQuickWindow,
]:
    engine = QQmlApplicationEngine()
    engine.addImportPath(str(Path(native_glass_lab_qml_path()).parent))
    facade = MockNovelStudioFacade()
    theme = ThemeProvider()
    register_frontend_types(engine, facade, theme)
    bridge = FakeNativeGlassBridge()
    engine.rootContext().setContextProperty("NativeGlassBridge", bridge)
    engine.load(QUrl.fromLocalFile(str(native_glass_lab_qml_path())))
    assert engine.rootObjects(), "NativeGlassLab.qml failed to load"
    window = engine.rootObjects()[0]
    assert isinstance(window, QQuickWindow)
    window.resize(1280, 820)
    window.show()
    qtbot.wait(30)  # visible-change auto-apply + first layout settle
    _ACTIVE_ENGINES.append(engine)
    return engine, facade, theme, bridge, window


def _content(window: QQuickWindow) -> QQuickItem:
    content = window.contentItem()
    assert isinstance(content, QQuickItem)
    return content


def _click(window: QQuickWindow, name: str) -> None:
    item = _find_item(_content(window), name)
    assert item is not None, f"missing control {name}"
    QMetaObject.invokeMethod(item, "clicked")


def _scene_rect(item: QQuickItem) -> QRectF:
    top_left = item.mapToScene(QPointF(0.0, 0.0))
    bottom_right = item.mapToScene(QPointF(item.width(), item.height()))
    return QRectF(
        top_left.x(),
        top_left.y(),
        bottom_right.x() - top_left.x(),
        bottom_right.y() - top_left.y(),
    )


def _qcolor(value: object) -> QColor:
    if isinstance(value, QColor):
        return value
    return QColor(str(value))


def test_native_glass_lab_loads(qtbot: QtBot) -> None:
    engine, _, _, _, window = _load_lab(qtbot)
    assert len(engine.rootObjects()) == 1
    assert window.objectName() == "nativeGlassWindow"
    assert window.title() == "AI Novel Studio \u00b7 Native Glass Lab"


def test_default_state_native_acrylic_not_active(qtbot: QtBot) -> None:
    _, _, _, bridge, window = _load_lab(qtbot)
    assert bridge.apply_result is False
    assert window.property("mode") == "native"
    assert window.property("nativeKind") == "acrylic"
    assert window.property("nativeActive") is False
    assert window.property("activeKind") == "none"
    assert _qcolor(window.color()).alpha() == 255


def test_internal_mode_is_opaque(qtbot: QtBot) -> None:
    _, _, _, bridge, window = _load_lab(qtbot)
    _click(window, "ngModeInternal")
    qtbot.waitUntil(lambda: window.property("mode") == "internal")
    assert window.property("nativeActive") is False
    assert bridge.calls[-1] == "none"
    qtbot.waitUntil(lambda: _qcolor(window.color()).alpha() == 255)


def test_native_apply_success_turns_window_transparent(qtbot: QtBot) -> None:
    _, _, _, bridge, window = _load_lab(qtbot)
    bridge.apply_result = True
    _click(window, "ngModeNative")
    qtbot.waitUntil(lambda: bool(window.property("nativeActive")) is True)
    assert window.property("activeKind") == "acrylic"
    qtbot.waitUntil(lambda: _qcolor(window.color()).alpha() == 0)


def test_native_apply_failure_stays_on_fallback(qtbot: QtBot) -> None:
    _, _, _, bridge, window = _load_lab(qtbot)
    assert bridge.apply_result is False
    _click(window, "ngModeNative")  # explicit DWM-failure attempt
    qtbot.waitUntil(lambda: bridge.calls[-1] == "acrylic")
    assert window.property("nativeActive") is False
    assert window.property("activeKind") == "none"
    assert _qcolor(window.color()).alpha() == 255


def test_switch_native_kind_mica_reaches_bridge(qtbot: QtBot) -> None:
    _, _, _, bridge, window = _load_lab(qtbot)
    _click(window, "ngMicaButton")
    qtbot.waitUntil(lambda: window.property("nativeKind") == "mica")
    assert bridge.calls[-1] == "mica"


def test_theme_switch_updates_theme_provider_and_window_color(
    qtbot: QtBot,
) -> None:
    _, _, theme, bridge, window = _load_lab(qtbot)

    def canvas_color() -> str:
        tokens = theme.property("tokens")
        return str(tokens["color"]["bgCanvas"]).upper()

    _click(window, "ngThemeButton")  # dark -> light
    qtbot.waitUntil(lambda: theme.property("themeName") == "light")
    assert window.property("themeName") == "light"
    qtbot.waitUntil(
        lambda: _qcolor(window.color()).name().upper() == canvas_color()
    )
    assert bridge.dark_mode_calls[-1] is False
    _click(window, "ngThemeButton")  # light -> dark
    qtbot.waitUntil(lambda: theme.property("themeName") == "dark")
    qtbot.waitUntil(
        lambda: _qcolor(window.color()).name().upper() == canvas_color()
    )
    assert bridge.dark_mode_calls[-1] is True


def test_three_column_body_layout(qtbot: QtBot) -> None:
    _, _, _, _, window = _load_lab(qtbot)
    qtbot.wait(50)  # offscreen layout settles after the first show
    content = _content(window)
    names = ("ngNavPanel", "ngChapterPanel", "ngManuscript", "ngAgentPanel")
    rects: dict[str, QRectF] = {}
    for name in names:
        item = _find_item(content, name)
        assert item is not None, f"missing {name}"
        assert float(item.width()) > 0 and float(item.height()) > 0, name
        rects[name] = _scene_rect(item)
    for name, rect in rects.items():
        assert rect.left() >= -0.5, name
        assert rect.top() >= -0.5, name
        assert rect.right() <= float(window.width()) + 0.5, name
        assert rect.bottom() <= float(window.height()) + 0.5, name
    for i, name_a in enumerate(names):
        for name_b in names[i + 1 :]:
            a = rects[name_a]
            b = rects[name_b]
            assert (
                a.right() <= b.left() + 0.5 or b.right() <= a.left() + 0.5
            ), f"{name_a} overlaps {name_b}: {a} vs {b}"


def test_manuscript_text_long_enough(qtbot: QtBot) -> None:
    _, _, _, _, window = _load_lab(qtbot)
    manuscript = _find_item(_content(window), "ngManuscriptText")
    assert manuscript is not None
    body = str(manuscript.property("text"))
    assert len(body) > 300


def test_status_bar_at_window_bottom(qtbot: QtBot) -> None:
    _, _, _, _, window = _load_lab(qtbot)
    status = _find_item(_content(window), "ngStatusBar")
    assert status is not None
    bottom = float(status.y()) + float(status.height())
    assert abs(bottom - float(window.height())) < 2
