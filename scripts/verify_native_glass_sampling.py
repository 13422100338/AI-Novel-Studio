"""Decisive "is the wallpaper really sampled" probe for the Native Glass Lab.

Run while ``stripe_backdrop_window.py --split`` is on screen (left half red,
right half cyan). The lab window is moved across the two halves and the
background strip inside its title bar is measured each time:

  - if the strip color follows the half under the window (red -> cyan), the
    DWM Desktop Acrylic material IS sampling window-behind content (glass is
    real; the previous flat look was just over-blurred stripes/wallpaper);
  - if the strip stays identical, the material is only applying a static tint
    and never samples the desktop.

Usage:
    1. .\.venv\Scripts\python.exe scripts\stripe_backdrop_window.py --split --seconds 600
    2. .\.venv\Scripts\python.exe scripts\verify_native_glass_sampling.py
"""

from __future__ import annotations

import statistics
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from PySide6.QtCore import QUrl  # noqa: E402
from PySide6.QtGui import QGuiApplication  # noqa: E402
from PySide6.QtQml import QQmlApplicationEngine  # noqa: E402
from PySide6.QtQuick import QQuickWindow  # noqa: E402

from ai_novel_studio.ui_qml.bootstrap import (  # noqa: E402
    NativeGlassBridge,
    native_glass_lab_qml_path,
    register_frontend_types,
)


def _pump(app: QGuiApplication, rounds: int = 8) -> None:
    for _ in range(rounds):
        app.processEvents()
        time.sleep(0.03)


def _strip_stats(
    image,
    x0f: float,
    x1f: float,
    y0f: float,
    y1f: float,
) -> dict[str, object]:
    x0 = round(image.width() * x0f)
    x1 = round(image.width() * x1f)
    y0 = round(image.height() * y0f)
    y1 = round(image.height() * y1f)
    colors: set[tuple[int, int, int]] = set()
    rs: list[int] = []
    gs: list[int] = []
    bs: list[int] = []
    for y in range(y0, y1):
        for x in range(x0, x1):
            c = image.pixelColor(x, y)
            colors.add((c.red(), c.green(), c.blue()))
            rs.append(c.red())
            gs.append(c.green())
            bs.append(c.blue())
    return {
        "unique": len(colors),
        "mean": (
            round(statistics.fmean(rs), 1),
            round(statistics.fmean(gs), 1),
            round(statistics.fmean(bs), 1),
        ),
        "std": (
            round(statistics.pstdev(rs), 1),
            round(statistics.pstdev(gs), 1),
            round(statistics.pstdev(bs), 1),
        ),
    }


def main() -> int:
    app = QGuiApplication(sys.argv)
    engine = QQmlApplicationEngine()
    engine.addImportPath(str(Path(native_glass_lab_qml_path()).parent))
    _, theme = register_frontend_types(engine)
    QQuickWindow.setDefaultAlphaBuffer(True)
    bridge = NativeGlassBridge(engine)
    engine.rootContext().setContextProperty("NativeGlassBridge", bridge)
    engine.load(QUrl.fromLocalFile(str(native_glass_lab_qml_path())))
    if not engine.rootObjects():
        raise RuntimeError("NativeGlassLab.qml failed to load")
    root = engine.rootObjects()[0]
    assert isinstance(root, QQuickWindow)
    bridge.setWindow(root)
    theme.setTheme("dark")
    bridge.setDarkMode(True)
    root.raise_()
    root.requestActivate()
    root.show()
    _pump(app, 8)
    time.sleep(1.0)
    root.raise_()
    root.requestActivate()
    _pump(app, 8)
    for _ in range(30):
        if bool(root.property("nativeActive")):
            break
        root.raise_()
        root.requestActivate()
        _pump(app, 4)
        time.sleep(0.15)
    print(f"nativeActive={bool(root.property('nativeActive'))}")

    screen = root.screen() or QGuiApplication.primaryScreen()
    assert screen is not None
    screen_geo = screen.geometry()
    dpr = float(screen.devicePixelRatio())

    for xpos in (0, 256, 0):
        root.setPosition(xpos, 78)
        _pump(app, 8)
        time.sleep(0.6)
        _pump(app, 4)
        full = screen.grabWindow(0).toImage()
        geo = root.geometry()
        x = round((geo.x() - screen_geo.x()) * dpr)
        y = round((geo.y() - screen_geo.y()) * dpr)
        width = round(geo.width() * dpr)
        height = round(geo.height() * dpr)
        crop = full.copy(x, y, width, height)
        # Window is 1280 wide on a 1536 screen: x=0 -> strip (55..75%) sits
        # across the red/cyan border; x=256 -> the same in-window strip lies
        # fully inside the cyan half. A color change proves DWM sampling.
        inside = _strip_stats(crop, 0.55, 0.75, 0.015, 0.037)
        print(f"x={xpos}: title-bar strip {inside}")

    engine.deleteLater()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
