"""Capture Frontend Wave F1 screenshots (offscreen, software rendering).

Usage (from the worktree root, using its venv):
    .\\.venv\\Scripts\\python.exe scripts\\capture_frontend_f1_screenshots.py

Outputs PNGs into docs/frontend/screenshots/.
"""

from __future__ import annotations

import os
import sys
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


def main() -> int:
    app = QGuiApplication([])
    app.setApplicationName("AI Novel Studio F1 Screenshot")
    engine = create_engine()
    if not engine.rootObjects():
        print("App.qml failed to load", file=sys.stderr)
        return 1
    engine.rootObjects()[0].show()
    _pump(app)
    quick_windows = [w for w in app.topLevelWindows() if isinstance(w, QQuickWindow)]
    if not quick_windows:
        print("No QQuickWindow available", file=sys.stderr)
        return 1
    window = quick_windows[0]
    facade = engine.rootContext().contextProperty("Facade")
    theme = engine.rootContext().contextProperty("Theme")
    out_dir = Path(__file__).resolve().parent.parent / "docs" / "frontend" / "screenshots"
    out_dir.mkdir(parents=True, exist_ok=True)

    for theme_name in ("paper", "light", "dark"):
        theme.setTheme(theme_name)
        _pump(app)
        target = out_dir / f"01-shell-{theme_name}.png"
        saved = window.grabWindow().save(str(target))
        print(f"{'OK  ' if saved else 'FAIL'} {target.name}")

    facade.requestDraft()
    theme.setTheme("paper")
    _pump(app)
    target = out_dir / "02-shell-paper-ai-drawer.png"
    saved = window.grabWindow().save(str(target))
    print(f"{'OK  ' if saved else 'FAIL'} {target.name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
