"""Windowed evidence capture for the production shell's native-glass mode.

Loads App.qml with the real NativeGlassBridge (same wiring as
``python -m ai_novel_studio.ui_qml``) and saves:

  - glass-shell-acrylic-dark.png / -composed.png / -screen.png
    (DWM Desktop Acrylic enabled, dark theme);
  - glass-shell-solid-dark.png / -composed.png / -screen.png
    (--no-glass control: fully opaque shell).

The -screen.png evidence includes the DWM blur layer and prints a
title-bar background strip statistic: a flat strip means the material only
applies a static tint; texture there means the desktop is really sampled.

Usage (lab window NOT running; desktop must not be covered by a fullscreen
exclusive game):
    .\\.venv\\Scripts\\python.exe scripts\\capture_glass_shell.py
"""

from __future__ import annotations

import os
import sys
import time
from pathlib import Path

os.environ.setdefault("QT_QUICK_CONTROLS_STYLE", "Basic")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

if "--windowed" not in sys.argv:
    # capture_native_glass_lab decides its platform from sys.argv: without
    # this marker its module-level code would force QT_QPA_PLATFORM=offscreen
    # and the DWM material could never be attached. Qt ignores the flag.
    sys.argv.append("--windowed")

from capture_native_glass_lab import (  # noqa: E402
    _capture_print_window,
    _print_background_strip_stats,
    _pump,
)
from PySide6.QtCore import QUrl  # noqa: E402
from PySide6.QtGui import QGuiApplication  # noqa: E402
from PySide6.QtQml import QQmlApplicationEngine  # noqa: E402
from PySide6.QtQuick import QQuickWindow  # noqa: E402

from ai_novel_studio.ui_qml.bootstrap import (  # noqa: E402
    NativeGlassBridge,
    app_qml_path,
    register_frontend_types,
)

OUT_DIR = (
    Path(__file__).resolve().parent.parent
    / "docs"
    / "frontend"
    / "screenshots"
)


def _screen_crop(window: QQuickWindow):
    """DPR-corrected real-screen crop of the window's rectangle."""
    screen = window.screen()
    if screen is None:
        screen = QGuiApplication.primaryScreen()
    if screen is None:
        return None
    image = screen.grabWindow(0).toImage()
    if image.isNull():
        return None
    dpr = float(screen.devicePixelRatio())
    geo = window.geometry()
    screen_geo = screen.geometry()
    x = round((geo.x() - screen_geo.x()) * dpr)
    y = round((geo.y() - screen_geo.y()) * dpr)
    width = round(geo.width() * dpr)
    height = round(geo.height() * dpr)
    x = max(0, min(x, image.width() - 1))
    y = max(0, min(y, image.height() - 1))
    width = max(1, min(width, image.width() - x))
    height = max(1, min(height, image.height() - y))
    return image.copy(x, y, width, height)


def _capture_shell(app: QGuiApplication, stem: str, glass: bool) -> None:
    engine = QQmlApplicationEngine()
    engine.addImportPath(str(Path(app_qml_path()).parent))
    _, theme = register_frontend_types(engine)
    if glass:
        QQuickWindow.setDefaultAlphaBuffer(True)
        bridge = NativeGlassBridge(engine)
        engine.rootContext().setContextProperty("NativeGlassBridge", bridge)
    engine.rootContext().setContextProperty("UseNativeGlass", glass)
    engine.rootContext().setContextProperty("WritingPageUseWebEngine", False)
    engine.load(QUrl.fromLocalFile(str(app_qml_path())))
    if not engine.rootObjects():
        raise RuntimeError("App.qml failed to load")
    root = engine.rootObjects()[0]
    assert isinstance(root, QQuickWindow)
    if glass:
        bridge.setWindow(root)
        theme.setTheme("dark")
        bridge.setDarkMode(True)
        bridge.apply("acrylic")
    root.show()
    if glass:
        for _ in range(30):
            if bool(root.property("nativeActive")):
                break
            bridge.refresh()
            root.raise_()
            root.requestActivate()
            _pump(app, 4)
            time.sleep(0.15)
        print(f"  {stem}: nativeActive={bool(root.property('nativeActive'))}")
    _pump(app, 8)
    time.sleep(0.8)
    _pump(app, 4)

    content = root.grabWindow()
    assert not content.isNull(), "grabWindow returned null"
    content_path = OUT_DIR / f"glass-shell-{stem}.png"
    assert content.save(str(content_path)), f"failed to save {content_path}"
    print(f"  saved {content_path}")

    composed = _capture_print_window(root)
    if composed is not None and not composed.isNull():
        composed_path = OUT_DIR / f"glass-shell-{stem}-composed.png"
        assert composed.save(str(composed_path)), f"failed to save {composed_path}"
        print(f"  composed evidence: {composed_path}")

    screen = _screen_crop(root)
    if screen is not None and not screen.isNull():
        screen_path = OUT_DIR / f"glass-shell-{stem}-screen.png"
        assert screen.save(str(screen_path)), f"failed to save {screen_path}"
        _print_background_strip_stats(screen, stem)
    engine.deleteLater()


def main() -> int:
    app = QGuiApplication(sys.argv)
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    _capture_shell(app, "acrylic-dark", glass=True)
    _capture_shell(app, "solid-dark", glass=False)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
