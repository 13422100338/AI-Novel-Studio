"""Phase 1 editor runtime: script injection, asset staging, webengine hardening."""

from __future__ import annotations

import json
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

_EDITOR_WEB_DIR = Path(__file__).resolve().parent / "editor_web"
_DIST_DIR = _EDITOR_WEB_DIR / "dist"


@dataclass(frozen=True, slots=True)
class LoadDocumentPayload:
    chapterId: str
    baseRevision: int
    markdown: str


class WebEngineSettingsPort(Protocol):
    def setAttribute(self, attribute: object, on: bool) -> None: ...


def load_document_script(payload: LoadDocumentPayload) -> str:
    """Return a runJavaScript expression that loads a chapter into the page."""
    return (
        "window.__novelEditor && "
        "window.__novelEditor.loadDocument("
        + json.dumps(
            {
                "chapterId": payload.chapterId,
                "baseRevision": payload.baseRevision,
                "markdown": payload.markdown,
            },
            ensure_ascii=False,
        )
        + ")"
    )


def apply_theme_script(tokens: dict[str, str]) -> str:
    """Return a runJavaScript expression applying CSS variables to the editor."""
    return (
        "window.__novelEditor && "
        f"window.__novelEditor.applyTheme({json.dumps(tokens, ensure_ascii=False)})"
    )


def ensure_editor_dist() -> Path:
    """Build must run separately; this only verifies dist exists and returns it."""
    if not (_DIST_DIR / "editor.js").exists():
        raise RuntimeError(
            "editor_web/dist/editor.js 缺失：请在 ui_qml/editor_web 执行 npm run build"
        )
    return _DIST_DIR


def ensure_qwebchannel_js() -> None:
    """Copy the Qt LGPL qwebchannel.js client into dist if missing."""
    source = _EDITOR_WEB_DIR / "src" / "qwebchannel.js"
    target = _DIST_DIR / "qwebchannel.js"
    if not target.exists() and source.exists():
        _DIST_DIR.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, target)


def editor_index_url() -> str:
    return (ensure_editor_dist() / "index.html").as_uri()


def apply_webengine_hardening(settings: WebEngineSettingsPort) -> None:
    """Disable remote/content access per the product plan section 6.5.

    ``settings`` is a QWebEngineSettings instance; importing QtWebEngineCore is
    deferred so tests on offscreen platforms do not initialize WebEngine.
    """
    from PySide6.QtWebEngineCore import QWebEngineSettings

    settings.setAttribute(
        QWebEngineSettings.WebAttribute.LocalContentCanAccessRemoteUrls,
        False,
    )
    settings.setAttribute(
        QWebEngineSettings.WebAttribute.LocalContentCanAccessFileUrls,
        False,
    )
    settings.setAttribute(QWebEngineSettings.WebAttribute.LocalStorageEnabled, False)
    settings.setAttribute(
        QWebEngineSettings.WebAttribute.JavascriptCanOpenWindows,
        False,
    )
    settings.setAttribute(
        QWebEngineSettings.WebAttribute.JavascriptCanPaste,
        False,
    )
    settings.setAttribute(QWebEngineSettings.WebAttribute.DnsPrefetchEnabled, False)
    settings.setAttribute(QWebEngineSettings.WebAttribute.PluginsEnabled, False)
    settings.setAttribute(
        QWebEngineSettings.WebAttribute.FullScreenSupportEnabled,
        False,
    )
    settings.setAttribute(
        QWebEngineSettings.WebAttribute.ScreenCaptureEnabled,
        False,
    )
