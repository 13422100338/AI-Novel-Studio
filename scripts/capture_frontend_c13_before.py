"""Capture the C1.3 pre-fix overlap from the real App.qml (offscreen).

Runs three full Mock Agent turns through the real TextArea-mode shell and
grabs the whole window, so the overlap of zero-height timeline cards is
visible exactly as in production. Used only for the before/after report.
"""

from __future__ import annotations

import os
import sys
import time
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QT_QUICK_BACKEND", "software")

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from PySide6.QtGui import QGuiApplication  # noqa: E402
from PySide6.QtQuick import QQuickWindow  # noqa: E402

from ai_novel_studio.ui_qml.bootstrap import create_engine  # noqa: E402


def _pump(app: QGuiApplication, rounds: int = 10) -> None:
    for _ in range(rounds):
        app.processEvents()


def _run_agent_turn(app: QGuiApplication, facade: object, prompt: str) -> None:
    facade.startAgentTurn(prompt)
    deadline = time.monotonic() + 8.0
    while time.monotonic() < deadline and facade.property("agentBusy") is True:
        app.processEvents()
        time.sleep(0.02)
    _pump(app, 20)


def main() -> int:
    app = QGuiApplication([])
    app.setApplicationName("AI Novel Studio C1.3 Before")
    engine = create_engine()
    if not engine.rootObjects():
        print("App.qml failed to load", file=sys.stderr)
        return 1
    root = engine.rootObjects()[0]
    root.show()
    _pump(app)
    quick_windows = [w for w in app.topLevelWindows() if isinstance(w, QQuickWindow)]
    if not quick_windows:
        print("No QQuickWindow available", file=sys.stderr)
        return 1
    window = quick_windows[0]
    facade = engine.rootContext().contextProperty("Facade")

    facade.toggleAiDrawer(True)
    _pump(app)
    _run_agent_turn(app, facade, "扩写：让人物说话更自然，并保留雾港清晨的意象。")
    _run_agent_turn(app, facade, "精简：把这一段压缩到一半长度。")
    _run_agent_turn(app, facade, "重写：让林默的对话更有克制感。")

    out_dir = Path(__file__).resolve().parent.parent / "docs" / "frontend" / "screenshots"
    out_dir.mkdir(parents=True, exist_ok=True)
    target = out_dir / "c1.3-before-real-multi-turn.png"
    saved = window.grabWindow().save(str(target))
    if not saved:
        print("failed to save before screenshot", file=sys.stderr)
        return 1
    print(f"OK   {target.name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
