"""Application bootstrap for the QML shell (Frontend Wave F1)."""

from __future__ import annotations

import sys
from collections.abc import Sequence
from pathlib import Path

from PySide6.QtCore import QUrl
from PySide6.QtGui import QGuiApplication
from PySide6.QtQml import QQmlApplicationEngine

from ai_novel_studio.ui_qml.bridge.mock_novel_studio_facade import MockNovelStudioFacade
from ai_novel_studio.ui_qml.bridge.theme_provider import ThemeProvider
from ai_novel_studio.ui_qml.editor_runtime import ensure_editor_dist, ensure_qwebchannel_js

_FRONTEND_STATE: dict[int, tuple[MockNovelStudioFacade, ThemeProvider]] = {}


def register_frontend_types(
    engine: QQmlApplicationEngine,
    facade: MockNovelStudioFacade | None = None,
    theme: ThemeProvider | None = None,
) -> tuple[MockNovelStudioFacade, ThemeProvider]:
    """Expose the two F1 singletons to QML.

    Context properties are used deliberately instead of ``qmlRegisterSingletonType``:
    QML type registration is process-global, while tests need a fresh facade per
    engine. Only two well-named singletons exist, so this stays far from the
    "many implicit globals" the architecture plan warns about. The packaging ticket
    (F6) will move to a qmldir-backed typed registration for the single-process app.
    """
    facade = facade if facade is not None else MockNovelStudioFacade()
    theme = theme if theme is not None else ThemeProvider()
    engine.rootContext().setContextProperty("Facade", facade)
    engine.rootContext().setContextProperty("Theme", theme)
    engine.rootContext().setContextProperty("WritingPageUseWebEngine", False)
    return facade, theme


def app_qml_path() -> Path:
    return Path(__file__).resolve().parent / "qml" / "App.qml"


def create_engine() -> QQmlApplicationEngine:
    """Build the TextArea-mode shell (tests and screenshot baseline)."""
    engine = QQmlApplicationEngine()
    engine.addImportPath(str(Path(__file__).resolve().parent / "qml"))
    facade, theme = register_frontend_types(engine)
    # Keep Python-side references alive for the engine's lifetime; otherwise the
    # QObject wrappers can be garbage collected and QML sees null singletons.
    _FRONTEND_STATE[id(engine)] = (facade, theme)
    engine.load(QUrl.fromLocalFile(str(app_qml_path())))
    return engine


def main(argv: Sequence[str] | None = None) -> int:
    args = list(argv) if argv is not None else sys.argv
    use_webengine = "--textarea" not in args
    args = [arg for arg in args if arg != "--textarea"]
    if use_webengine:
        from PySide6.QtWebEngineQuick import QtWebEngineQuick

        ensure_editor_dist()
        ensure_qwebchannel_js()
        QtWebEngineQuick.initialize()

    app = QGuiApplication(args)
    app.setApplicationName("AI Novel Studio (QML F1)")
    app.setOrganizationName("AI Novel Studio")
    engine = QQmlApplicationEngine()
    engine.addImportPath(str(Path(__file__).resolve().parent / "qml"))
    facade, theme = register_frontend_types(engine)
    engine.rootContext().setContextProperty("WritingPageUseWebEngine", use_webengine)
    if use_webengine:
        from ai_novel_studio.ui_qml.bridge.editor_bridge import EditorBridge

        editor_bridge = EditorBridge(engine)
        editor_bridge.save_requested.connect(
            lambda chapter_id, revision, markdown, content_hash: facade.saveFromEditor(
                chapter_id, revision, markdown
            )
        )
        editor_bridge.error.connect(facade.setSaveStatusText)
        editor_bridge.word_count_changed.connect(facade.setWebEngineWordCount)
        engine.rootContext().setContextProperty("pythonBridge", editor_bridge)
    _FRONTEND_STATE[id(engine)] = (facade, theme)
    engine.load(QUrl.fromLocalFile(str(app_qml_path())))
    if not engine.rootObjects():
        return 1
    return app.exec()
