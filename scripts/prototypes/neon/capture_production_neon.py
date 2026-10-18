"""Capture the production run_status neon border for delivery evidence.

Loads the real F1 shell, opens the AI dock, starts a Mock turn and grabs:
  1. thinking state (busy run_status with looping neon border);
  2. success state (DONE run_status after the sweep).
Windowed only (ShaderEffect needs a real graphics stack).
"""

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

ROOT = Path(__file__).resolve().parent.parent.parent.parent
OUT = (
    ROOT
    / "docs"
    / "frontend"
    / "screenshots"
)


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


def to_pil(image: object) -> Image.Image:
    width = image.width()
    height = image.height()
    buffer = bytes(image.constBits())
    return Image.frombytes("RGBA", (width, height), buffer).convert("RGB")


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

    OUT.mkdir(parents=True, exist_ok=True)
    facade.toggleAiDrawer(True)
    pump_seconds(app, 0.5)
    facade.startAgentTurn("帮我重写这段，让人物说话更自然。")

    # Wait for the first run_status neon (thinking loop) and capture.
    deadline = time.monotonic() + 8.0
    while time.monotonic() < deadline:
        pump_seconds(app, 0.05)
        items = find_all(window.contentItem(), "agentRunStatusNeon")
        if items and bool(items[0].property("active")):
            break
    pump_seconds(app, 0.4)
    shot = to_pil(window.grabWindow())
    thinking = OUT / "c1-neon-thinking.png"
    shot.save(str(thinking))
    print("saved", thinking)

    # Wait for the DONE run_status success sweep and capture.
    deadline = time.monotonic() + 12.0
    saw_success = False
    while time.monotonic() < deadline:
        pump_seconds(app, 0.05)
        items = find_all(window.contentItem(), "agentRunStatusNeon")
        if any(item.property("state") == "success" for item in items):
            saw_success = True
            break
    assert saw_success, "success state never appeared"
    pump_seconds(app, 0.3)
    shot = to_pil(window.grabWindow())
    success = OUT / "c1-neon-success.png"
    shot.save(str(success))
    print("saved", success)

    engine.deleteLater()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
