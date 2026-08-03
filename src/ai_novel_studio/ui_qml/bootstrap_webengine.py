"""WebEngine-aware application entry (Phase 1 real-device slice).

``QtWebEngineQuick.initialize()`` MUST run before the QGuiApplication is
created, so this module cannot share the plain QML bootstrap's ``main()``.
"""

from __future__ import annotations

import sys
from collections.abc import Sequence
from pathlib import Path

from PySide6.QtCore import Property, QObject, QUrl
from PySide6.QtGui import QGuiApplication
from PySide6.QtQml import QQmlApplicationEngine
from PySide6.QtWebEngineQuick import QtWebEngineQuick

from ai_novel_studio.ui_qml.bridge.editor_bridge import EditorBridge
from ai_novel_studio.ui_qml.bridge.mock_novel_studio_facade import MockNovelStudioFacade
from ai_novel_studio.ui_qml.bridge.theme_provider import ThemeProvider
from ai_novel_studio.ui_qml.editor_runtime import ensure_editor_dist, ensure_qwebchannel_js


class EditorAssets(QObject):
    """Exposes the local editor page URL to QML."""

    def __init__(self, index_url: str, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._index_url = index_url

    @Property(str, constant=True)
    def indexUrl(self) -> str:
        return self._index_url


def main(argv: Sequence[str] | None = None) -> int:
    ensure_qwebchannel_js()
    dist = ensure_editor_dist()
    QtWebEngineQuick.initialize()

    app = QGuiApplication(list(argv) if argv is not None else sys.argv)
    app.setApplicationName("AI Novel Studio (QML WebEngine F1)")
    app.setOrganizationName("AI Novel Studio")

    engine = QQmlApplicationEngine()
    engine.addImportPath(str(Path(__file__).resolve().parent / "qml"))
    facade = MockNovelStudioFacade()
    theme = ThemeProvider()
    editor_bridge = EditorBridge(engine)
    editor_bridge.save_requested.connect(
        lambda chapter_id, revision, markdown, content_hash: facade.saveFromEditor(
            chapter_id, revision, markdown
        )
    )
    editor_bridge.error.connect(facade.setSaveStatusText)
    engine.rootContext().setContextProperty("Facade", facade)
    engine.rootContext().setContextProperty("Theme", theme)
    # The QML side creates its own WebChannel (QQmlWebChannel) and registers
    # this Python QObject into it; QML WebEngineView only accepts QQmlWebChannel.
    engine.rootContext().setContextProperty("pythonBridge", editor_bridge)
    engine.rootContext().setContextProperty(
        "EditorAssets",
        EditorAssets((dist / "index.html").as_uri(), engine),
    )
    qml_root = Path(__file__).resolve().parent / "qml"
    engine.load(QUrl.fromLocalFile(str(qml_root / "AppWebEngine.qml")))
    if not engine.rootObjects():
        return 1
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
