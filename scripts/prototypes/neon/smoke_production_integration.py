"""Smoke test: production App + Mock agent turn with the shader neon border.

Loads the real F1 shell, opens the AI dock, starts a Mock turn and waits
until the run_status card appears with its StreamingGlowBorder running the
thinking loop. Then lets the turn finish and asserts the success sweep.
Windowed only (ShaderEffect needs a real graphics stack).
"""

from __future__ import annotations

import os
import time
from pathlib import Path

os.environ.setdefault("QT_QUICK_CONTROLS_STYLE", "Basic")

from PySide6.QtCore import QUrl  # noqa: E402
from PySide6.QtGui import QGuiApplication  # noqa: E402
from PySide6.QtQml import QQmlApplicationEngine  # noqa: E402
from PySide6.QtQuick import QQuickWindow  # noqa: E402

from ai_novel_studio.ui_qml.bootstrap import app_qml_path, register_frontend_types
from ai_novel_studio.ui_qml.bridge.mock_novel_studio_facade import MockNovelStudioFacade
from ai_novel_studio.ui_qml.bridge.theme_provider import ThemeProvider

ROOT = Path(__file__).resolve().parent.parent.parent.parent


def find_item(root: object, name: str) -> object | None:
    if getattr(root, "objectName", lambda: "")() == name:
        return root
    for child in root.childItems():  # type: ignore[attr-defined]
        found = find_item(child, name)
        if found is not None:
            return found
    return None


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

    # Open the AI dock and start a Mock turn.
    facade.toggleAiDrawer(True)
    pump_seconds(app, 0.4)
    facade.startAgentTurn("帮我重写这段，让人物说话更自然。")

    # Wait for the run_status card's neon border to appear in thinking loop.
    neon = None
    deadline = time.monotonic() + 8.0
    while time.monotonic() < deadline:
        pump_seconds(app, 0.05)
        neon = find_item(window.contentItem(), "agentRunStatusNeon")
        if neon is not None and bool(neon.property("active")):
            break
    assert neon is not None, "run_status neon border not found"
    print("run_status neon found; active:", neon.property("active"))
    print("state:", neon.property("state"))
    print("loopAnimRunning:", neon.property("loopAnimRunning"))
    assert neon.property("state") == "thinking"
    assert bool(neon.property("loopAnimRunning")) is True
    print("SMOKE PASS: thinking loop on production run_status card")

    # Let the turn finish; the second run_status (busy=False, status=DONE)
    # should sweep success once.
    deadline = time.monotonic() + 12.0
    saw_success = False
    while time.monotonic() < deadline:
        pump_seconds(app, 0.05)
        items = find_all(window.contentItem(), "agentRunStatusNeon")
        for item in items:
            if item.property("state") == "success":
                saw_success = True
                break
        if saw_success:
            break
    assert saw_success, "run_status never reached success state"
    print("SMOKE PASS: success sweep on production run_status card")

    engine.deleteLater()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
