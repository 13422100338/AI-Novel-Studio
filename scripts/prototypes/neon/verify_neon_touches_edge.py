"""Verify the neon light point hugs the card edge (regression: it was
inset by 2x the corner radius because the shader used hb-r as the rounded
rect half-extent)."""

from __future__ import annotations

import os
import time
from pathlib import Path

os.environ.setdefault("QT_QUICK_CONTROLS_STYLE", "Basic")

from PIL import Image  # type: ignore[import-untyped]
from PySide6.QtCore import QUrl  # noqa: E402
from PySide6.QtGui import QGuiApplication  # noqa: E402
from PySide6.QtQml import QQmlApplicationEngine  # noqa: E402
from PySide6.QtQuick import QQuickWindow  # noqa: E402

from ai_novel_studio.ui_qml.bootstrap import app_qml_path, register_frontend_types
from ai_novel_studio.ui_qml.bridge.mock_novel_studio_facade import MockNovelStudioFacade
from ai_novel_studio.ui_qml.bridge.theme_provider import ThemeProvider


def find_all(root: object, name: str) -> list[object]:
    matches: list[object] = []
    if getattr(root, "objectName", lambda: "")() == name:
        matches.append(root)
    for child in root.childItems():  # type: ignore[attr-defined]
        matches.extend(find_all(child, name))
    return matches


def pump_seconds(app: QGuiApplication, seconds: float) -> None:
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        app.processEvents()
        time.sleep(0.008)


def main() -> int:
    app = QGuiApplication([])
    engine = QQmlApplicationEngine()
    engine.addImportPath(str(Path(app_qml_path()).parent))
    facade = MockNovelStudioFacade()
    theme = ThemeProvider()
    register_frontend_types(engine, facade, theme)
    engine.load(QUrl.fromLocalFile(str(app_qml_path())))
    assert engine.rootObjects(), "App.qml failed to load"
    window = next(obj for obj in engine.rootObjects() if isinstance(obj, QQuickWindow))
    window.resize(1440, 900)
    window.show()
    pump_seconds(app, 1.0)

    facade.toggleAiDrawer(True)
    pump_seconds(app, 0.5)
    facade.startAgentTurn("帮我重写这段，让人物说话更自然。")

    neon = None
    deadline = time.monotonic() + 8.0
    while time.monotonic() < deadline:
        pump_seconds(app, 0.05)
        items = find_all(window.contentItem(), "agentRunStatusNeon")
        if items and bool(items[0].property("active")):
            neon = items[0]
            break
    assert neon is not None, "run_status neon not found"

    # Geometry of the run_status card in window (device px at DPR 2).
    card = neon.parentItem()
    dpr = float(window.devicePixelRatio())
    card_top_left = card.mapToItem(window.contentItem(), 0, 0)
    card_x = card_top_left.x() * dpr
    card_y = card_top_left.y() * dpr
    card_w = card.width() * dpr
    card_h = card.height() * dpr

    pump_seconds(app, 0.3)
    img = window.grabWindow()
    shot = Image.frombytes(
        "RGBA", (img.width(), img.height()), bytes(img.constBits())
    ).convert("RGB")

    # Locate the brightest pixel inside the card region (neon core).
    best = None
    for y in range(int(card_y), int(card_y + card_h)):
        for x in range(int(card_x), int(card_x + card_w)):
            r, g, b = shot.getpixel((x, y))
            v = r + g + b
            if best is None or v > best[0]:
                best = (v, x, y)
    assert best is not None
    _, px, py = best
    print(f"card rect: x={card_x:.0f} y={card_y:.0f} w={card_w:.0f} h={card_h:.0f}")
    print(f"brightest pixel: ({px}, {py}) brightness={best[0]}")

    # Distance from the core to the nearest card edge (device px).
    dist = min(
        px - card_x,
        card_x + card_w - px,
        py - card_y,
        card_y + card_h - py,
    )
    logical = dist / dpr
    print(f"edge distance: {dist:.1f} device px = {logical:.2f} logical px")

    # Halo visibility: sample the band outside the card (0..12 logical px)
    # and count pixels tinted by the neon color (blue-purple family) instead
    # of the plain background. The halo must be visible outside the edge.
    band = 12 * dpr
    halo_px = 0
    for y in range(int(card_y - band), int(card_y + card_h + band)):
        for x in range(int(card_x - band), int(card_x + card_w + band)):
            inside = (
                card_x <= x < card_x + card_w
                and card_y <= y < card_y + card_h
            )
            if inside:
                continue
            r, g, b = shot.getpixel((x, y))
            if b > 60 and b > r + 8:
                halo_px += 1
    print(f"halo pixels outside the card edge: {halo_px}")

    ok_edge = logical <= 3.0
    ok_halo = halo_px >= 200
    print("PASS" if ok_edge and ok_halo else "FAIL",
          f"- edge {'ok' if ok_edge else 'BAD'}, "
          f"halo {'ok' if ok_halo else 'NOT VISIBLE'}")
    engine.deleteLater()
    return 0 if ok_edge and ok_halo else 1


if __name__ == "__main__":
    raise SystemExit(main())
