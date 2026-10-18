"""Windows 11 system backdrop bridge (optional Visual V0 lab enhancement)."""

from __future__ import annotations

from PySide6.QtQuick import QQuickWindow

from ai_novel_studio.ui_qml.bridge import windows_backdrop as wb


def test_dwm_constants_match_windows_sdk() -> None:
    assert wb._DWMWA_SYSTEMBACKDROP_TYPE == 38
    assert wb.DWMSBT_MAINWINDOW == 2  # Mica
    assert wb.DWMSBT_TRANSIENTWINDOW == 3  # Desktop Acrylic
    assert wb.DWMSBT_TABBEDWINDOW == 4  # Mica Alt


def test_unknown_kind_rejected() -> None:
    assert wb.apply_system_backdrop(None, "sparkle") is False


def test_apply_never_raises_and_returns_bool() -> None:
    window = QQuickWindow()
    window.resize(320, 240)
    try:
        result = wb.apply_system_backdrop(window, "mica")
        assert isinstance(result, bool)
        result = wb.apply_system_backdrop(window, "acrylic")
        assert isinstance(result, bool)
    finally:
        window.deleteLater()
