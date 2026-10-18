"""Real-machine diagnostic for the Visual V0 system-backdrop (Mica) route.

Run on a real Windows 11 machine (NOT offscreen):

    .\\.venv\\Scripts\\python.exe scripts\\diagnose_windows_backdrop.py

It opens a small transparent QQuickWindow for a few seconds and prints:

- the active desktop wallpaper path;
- whether Qt made the window layered (WS_EX_LAYERED) -- layered windows are
  known to conflict with DWM system backdrops;
- the DwmSetWindowAttribute(DWMWA_SYSTEMBACKDROP_TYPE) result;
- the legacy SetWindowCompositionAttribute(Acrylic blur) result.

Findings from 2026-08-04 (logged in docs/frontend/2026-08-04-glassmorphism-ui-log.md):
DwmSetWindowAttribute(Mica) returned S_OK, the window was NOT layered, and the
flat gray pane was our own 0.8-opacity themed wash covering the DWM backdrop.
"""

from __future__ import annotations

import ctypes
import os
import time
from ctypes import wintypes

os.environ.pop("QT_QPA_PLATFORM", None)  # real window required

from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtGui import QColor, QGuiApplication  # noqa: E402
from PySide6.QtQuick import QQuickWindow  # noqa: E402

GWL_EXSTYLE = -20
WS_EX_LAYERED = 0x00080000
DWMWA_SYSTEMBACKDROP_TYPE = 38
DWMSBT_MAINWINDOW = 2  # Mica
SPI_GETDESKWALLPAPER = 0x0073


def main() -> int:
    user32 = ctypes.WinDLL("user32")
    dwmapi = ctypes.WinDLL("dwmapi")

    get_style = user32.GetWindowLongPtrW
    get_style.restype = ctypes.c_longlong
    get_style.argtypes = [wintypes.HWND, ctypes.c_int]

    def dwm_set(hwnd: int, kind: int) -> int:
        value = ctypes.c_int(kind)
        return int(
            dwmapi.DwmSetWindowAttribute(
                wintypes.HWND(int(hwnd)),
                ctypes.c_uint(DWMWA_SYSTEMBACKDROP_TYPE),
                ctypes.byref(value),
                ctypes.sizeof(value),
            )
        )

    def wca_set(hwnd: int, state: int) -> int:
        class AccentPolicy(ctypes.Structure):
            _fields_ = [
                ("AccentState", ctypes.c_int),
                ("AccentFlags", ctypes.c_int),
                ("GradientColor", ctypes.c_uint),
                ("AnimationId", ctypes.c_int),
            ]

        class WindowCompositionAttributeData(ctypes.Structure):
            _fields_ = [
                ("Attribute", ctypes.c_int),
                ("DataSize", ctypes.c_size_t),
                ("Data", ctypes.c_void_p),
            ]

        accent = AccentPolicy(state, 0, 0x99000000, 0)
        data = WindowCompositionAttributeData(
            19,
            ctypes.sizeof(accent),
            ctypes.cast(ctypes.byref(accent), ctypes.c_void_p),
        )
        return int(
            user32.SetWindowCompositionAttribute(
                wintypes.HWND(int(hwnd)), ctypes.byref(data)
            )
        )

    wallpaper = ctypes.create_unicode_buffer(520)
    user32.SystemParametersInfoW(SPI_GETDESKWALLPAPER, 520, wallpaper, 0)
    print("wallpaper path:", wallpaper.value or "(none/empty)")

    app = QGuiApplication([])
    window = QQuickWindow()
    window.resize(420, 300)
    window.setTitle("mica diag (closes itself)")
    window.setColor(QColor(Qt.GlobalColor.transparent))
    window.show()
    for _ in range(8):
        app.processEvents()
        time.sleep(0.03)

    hwnd = int(window.winId())
    ex_style = get_style(hwnd, GWL_EXSTYLE)
    print("WS_EX_LAYERED:", bool(ex_style & WS_EX_LAYERED), hex(ex_style))

    hr_mica = dwm_set(hwnd, DWMSBT_MAINWINDOW)
    ok = (hr_mica & 0x80000000) == 0
    print(
        "DwmSetWindowAttribute(Mica) hr:",
        hex(hr_mica & 0xFFFFFFFF),
        "S_OK" if ok else "FAILED",
    )

    hr_wca = wca_set(hwnd, 4)  # ACCENT_ENABLE_ACRYLICBLURBEHIND
    print(
        "SetWindowCompositionAttribute(AcrylicBlurBehind):",
        hr_wca,
        "ok" if hr_wca else "FAILED",
    )

    window.deleteLater()
    app.processEvents()
    print("done")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
