"""Exercise the real WebChannel/editor offscreen, without opening author data."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

os.environ["QT_QPA_PLATFORM"] = "offscreen"
os.environ.setdefault("QTWEBENGINE_CHROMIUM_FLAGS", "--disable-gpu")

from PySide6.QtCore import QTimer, QUrl
from PySide6.QtWebChannel import QWebChannel
from PySide6.QtWebEngineCore import QWebEnginePage, QWebEngineProfile
from PySide6.QtWebEngineWidgets import QWebEngineView
from PySide6.QtWidgets import QApplication

from ai_novel_studio.ui_qml.bridge.editor_bridge import EditorBridge
from ai_novel_studio.ui_qml.bridge.mock_novel_studio_facade import MockNovelStudioFacade


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=False)
    app = QApplication(["editor-selection-offscreen"])
    view = QWebEngineView()
    profile = QWebEngineProfile(view)  # Off-the-record; no desktop browser profile.
    page = QWebEnginePage(profile, view)
    view.setPage(page)
    view.resize(900, 640)
    bridge = EditorBridge(page)
    channel = QWebChannel(page)
    channel.registerObject("pythonBridge", bridge)
    page.setWebChannel(channel)
    facade = MockNovelStudioFacade(demo_mode=True)
    source = "清晨，灯塔门缓缓打开。\n\n窗边的信仍然没有拆开。\n\n\n"
    facade.editorTextChanged(source)
    bridge.chat_selection_changed.connect(facade.setChatSelectionJson)
    result = {"errors": []}
    bridge.error.connect(lambda code, message: result["errors"].append(code))

    def finish(value=None):
        if value:
            result.update(json.loads(value))
        result["has_quote"] = facade.hasSelectionReference
        result["quote_preview"] = facade.selectionReferencePreview
        result["buffer_unchanged"] = facade.currentChapterBody == source
        view.grab().save(str(args.output / "editor.png"))
        (args.output / "result.json").write_text(
            json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        app.exit(
            0
            if result.get("outline") == "none"
            and result["has_quote"]
            and result["buffer_unchanged"]
            else 1
        )

    def inspect():
        page.runJavaScript(
            """JSON.stringify({
            outline: getComputedStyle(document.querySelector('.ProseMirror')).outlineStyle,
            selected: window.__novelEditor.getSelectionText(),
            focused: document.activeElement.classList.contains('ProseMirror')
        })""",
            lambda value: (
                page.runJavaScript("document.activeElement.blur()"),
                QTimer.singleShot(100, lambda: finish(value)),
            ),
        )

    def ready(*_):
        payload = json.dumps(
            dict(
                chapterId=facade.currentChapterId,
                baseRevision=facade.currentRevision,
                markdown=source,
            ),
            ensure_ascii=False,
        )
        page.runJavaScript(
            f"window.__novelEditor.loadDocument({payload}); window.__novelEditor.revealRange(1, 12)"
        )
        QTimer.singleShot(500, inspect)

    bridge.editor_ready.connect(ready)
    path = (
        Path(__file__).resolve().parents[1]
        / "src/ai_novel_studio/ui_qml/editor_web/dist/index.html"
    )
    page.load(QUrl.fromLocalFile(str(path)))
    view.show()  # QT_QPA_PLATFORM=offscreen; never creates a desktop window.
    QTimer.singleShot(20_000, finish)
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
