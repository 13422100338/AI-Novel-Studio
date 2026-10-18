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
    """Verify dist exists and is not stale relative to src; return dist path.

    Raises RuntimeError with an actionable message when the bundle is missing
    or older than any tracked source file (mtime staleness check).
    """
    if not (_DIST_DIR / "editor.js").exists():
        raise RuntimeError(
            "editor_web/dist/editor.js 缺失：请在 ui_qml/editor_web 执行 npm run build"
        )
    _check_dist_staleness()
    return _DIST_DIR


def _latest_source_mtime() -> float:
    """Newest mtime across tracked editor source files (0 if none found)."""
    src_dir = _EDITOR_WEB_DIR / "src"
    tracked = [
        "editor.ts", "editor-core.ts", "markdown.ts",
        "schema.ts", "style.css", "index.html",
    ]
    latest = 0.0
    for name in tracked:
        p = src_dir / name
        if p.exists():
            latest = max(latest, p.stat().st_mtime)
    return latest


def _dist_mtime() -> float:
    js = _DIST_DIR / "editor.js"
    if js.exists():
        return js.stat().st_mtime
    return 0.0


def _check_dist_staleness() -> None:
    """Fail loudly when the dist bundle predates any source edit."""
    dist_mtime = _dist_mtime()
    src_mtime = _latest_source_mtime()
    if src_mtime > dist_mtime + 1.0:  # 1s tolerance for FS jitter
        raise RuntimeError(
            "editor_web/dist/editor.js 已过期（早于 src/ 的最后修改）。"
            "请在 ui_qml/editor_web 执行 npm run build 更新后重试。"
            f"src mtime={src_mtime:.3f} dist mtime={dist_mtime:.3f}"
        )


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
