"""Capture AgentDock states for the ideal-UI stability step (spec 10.1).

Offscreen, software rendering, TextArea-independent: loads AgentDock directly
in a harness so the one-step geometry switch, content fade, drag preview line
and commit-on-release behavior are all exercised without a WebEngine surface.

Usage (from the worktree root, using its venv):
    .\\.venv\\Scripts\\python.exe scripts\\capture_frontend_ideal_ui_dock.py
"""

from __future__ import annotations

import os
import sys
import time
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QT_QUICK_BACKEND", "software")

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from PySide6.QtCore import QByteArray, QMetaObject, QUrl  # noqa: E402
from PySide6.QtGui import QGuiApplication  # noqa: E402
from PySide6.QtQml import QQmlApplicationEngine  # noqa: E402
from PySide6.QtQuick import QQuickItem, QQuickWindow  # noqa: E402

from ai_novel_studio.ui_qml.bootstrap import app_qml_path, register_frontend_types  # noqa: E402
from ai_novel_studio.ui_qml.bridge.mock_novel_studio_facade import (
    MockNovelStudioFacade,  # noqa: E402
)
from ai_novel_studio.ui_qml.bridge.theme_provider import ThemeProvider  # noqa: E402

OUT_DIR = (
    Path(__file__).resolve().parent.parent
    / "docs"
    / "frontend"
    / "screenshots"
)

HARNESS = """
import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "components"
ApplicationWindow {
    width: 1440
    height: 900
    visible: true
    Rectangle {
        anchors.fill: parent
        color: Theme.tokens.color.bgCanvas
        RowLayout {
            anchors.fill: parent
            Rectangle {
                Layout.fillWidth: true
                Layout.fillHeight: true
                color: Theme.tokens.color.bgEditor
                border.color: Theme.tokens.color.border
                border.width: 1
                Text {
                    anchors.centerIn: parent
                    text: "正文工作区（WebEngine 替换面）"
                    color: Theme.tokens.color.textSecondary
                }
            }
            AgentDock {
                open: Facade.aiDrawerOpen
                windowWidth: 1440
                Layout.fillHeight: true
            }
        }
    }
}
"""


def _pump(app: QGuiApplication, rounds: int = 6) -> None:
    for _ in range(rounds):
        app.processEvents()
        time.sleep(0.02)


def _find_item(root: QQuickItem, name: str) -> QQuickItem | None:
    if root.objectName() == name:
        return root
    for child in root.childItems():
        found = _find_item(child, name)
        if found is not None:
            return found
    return None


def _save(window: QQuickWindow, name: str) -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    path = OUT_DIR / name
    image = window.grabWindow()
    assert image.save(str(path)), f"failed to save {path}"
    print(f"saved {path}")


def main() -> int:
    app = QGuiApplication(sys.argv)
    engine = QQmlApplicationEngine()
    engine.addImportPath(str(Path(app_qml_path()).parent))
    facade = MockNovelStudioFacade()
    theme = ThemeProvider()
    register_frontend_types(engine, facade, theme)
    engine.loadData(
        QByteArray(HARNESS.encode("utf-8")),
        QUrl.fromLocalFile(str(Path(app_qml_path()).parent / "dock-ideal-ui.qml")),
    )
    root = engine.rootObjects()[0]
    assert root is not None, "harness failed to load"
    root.show()
    _pump(app)
    assert isinstance(root, QQuickWindow), "ApplicationWindow root expected"
    window = root

    dock = _find_item(root.contentItem(), "agentDock")
    preview = _find_item(root.contentItem(), "agentDragPreview")
    assert dock is not None and preview is not None

    # 1. Collapsed expand tab.
    _save(window, "ideal-ui-dock-collapsed.png")

    # 2. Open via facade: one-step geometry + content fade-in.
    facade.toggleAiDrawer(True)
    _pump(app, 8)
    assert dock.property("width") == 420
    _save(window, "ideal-ui-dock-open.png")

    # 3. Drag preview: dock width must stay 420 while dragging.
    dock.setProperty("dragPointerX", 2.5)
    QMetaObject.invokeMethod(dock, "beginResizeDrag")
    dock.setProperty("dragPointerX", -60.0)
    QMetaObject.invokeMethod(dock, "updateResizeDrag")
    _pump(app, 4)
    assert dock.property("width") == 420
    assert preview.property("visible") is True
    _save(window, "ideal-ui-dock-drag-preview.png")

    # 4. Commit once on release: width jumps to 420 - (-60) = 480.
    QMetaObject.invokeMethod(dock, "commitResizeDrag")
    _pump(app, 4)
    assert dock.property("width") == 480
    _save(window, "ideal-ui-dock-committed.png")

    # 5. Close: geometry snaps back to the expand tab, content fades out.
    facade.toggleAiDrawer(False)
    _pump(app, 8)
    assert dock.property("width") == 34
    _save(window, "ideal-ui-dock-closed.png")

    engine.deleteLater()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
