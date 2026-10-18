"""Interactive runner for the neon prototypes (windowed).

Usage (worktree root):
    .\\.venv\\Scripts\\python.exe scripts\\prototypes\\neon\\run_prototype.py \
        prototype_a_pathinterpolator.qml
    .\\.venv\\Scripts\\python.exe scripts\\prototypes\\neon\\run_prototype.py prototype_b_shader.qml

Prototype B has clickable state buttons (thinking / success / error /
cancelled / idle) and reduceMotion / safe toggles. Close the window to exit.
"""

from __future__ import annotations

import sys
from pathlib import Path

from PySide6.QtCore import QUrl  # noqa: E402
from PySide6.QtGui import QGuiApplication  # noqa: E402
from PySide6.QtQml import QQmlApplicationEngine  # noqa: E402

ROOT = Path(__file__).resolve().parent


def main() -> int:
    if len(sys.argv) != 2:
        print("usage: run_prototype.py <qml-file>")
        return 2
    qml = ROOT / sys.argv[1]
    if not qml.exists():
        print(f"not found: {qml}")
        return 2

    app = QGuiApplication([])
    engine = QQmlApplicationEngine()
    engine.load(QUrl.fromLocalFile(str(qml)))
    if not engine.rootObjects():
        print("QML failed to load")
        return 1
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
