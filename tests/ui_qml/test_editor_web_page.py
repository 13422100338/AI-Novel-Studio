"""C1.5: static invariants preventing WebEngine black edge strips.

These tests read the editor page source and QML host wiring and assert the
contract that keeps QtWebEngine from painting the default black canvas:
explicit viewport sizing, no body overflow, theme-colored scrollbars, an
explicit WebEngineView background, and no animated AI-dock width changes in
WebEngine mode. The WebEngine itself cannot run offscreen, so the invariants
are verified at the source level here and exercised live by
scripts/verify_webengine_edges.py on a real display.
"""

from __future__ import annotations

from pathlib import Path

from ai_novel_studio.ui_qml.bootstrap import _use_webengine_from_args

_ROOT = Path(__file__).resolve().parents[2] / "src" / "ai_novel_studio" / "ui_qml"
_STYLE = _ROOT / "editor_web" / "src" / "style.css"
_EDITOR_TS = _ROOT / "editor_web" / "src" / "editor.ts"
_WEBVIEW_QML = _ROOT / "qml" / "components" / "NovelEditorView.qml"
_DOCK_QML = _ROOT / "qml" / "components" / "AgentDock.qml"
_APP_QML = _ROOT / "qml" / "App.qml"


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_viewport_fills_and_paints_editor_background() -> None:
    css = _read(_STYLE)
    for selector in ("html,", "body"):
        assert selector in css
    for rule in ("width: 100%;", "height: 100%;", "margin: 0;", "padding: 0;"):
        assert rule in css, f"missing viewport rule {rule!r}"
    assert "background: var(--editor-bg, #fffdf7);" in css
    assert "overflow: hidden;" in css, "body must not render its own scrollbar"


def test_global_border_box_and_mount_sizing() -> None:
    css = _read(_STYLE)
    assert "box-sizing: border-box;" in css
    assert "#editor-mount" in css
    for rule in ("width: 100%;", "height: 100%;", "min-height: 100%;"):
        assert rule in css
    assert "overflow-x: hidden;" in css, "horizontal scrolling must be forbidden"


def test_scrollbars_use_editor_theme_colors() -> None:
    css = _read(_STYLE)
    assert "::-webkit-scrollbar {" in css
    assert "::-webkit-scrollbar-track {" in css
    assert "::-webkit-scrollbar-thumb {" in css
    assert "background: var(--editor-bg, #fffdf7);" in css
    assert "background: var(--editor-muted, #6e6a61);" in css


def test_theme_propagates_to_page_root_and_mount() -> None:
    ts = _read(_EDITOR_TS)
    assert "document.documentElement" in ts
    assert 'document.getElementById("editor-mount")' in ts
    assert "root.style.setProperty(key, value)" in ts


def test_loading_a_document_reports_its_word_count_back_to_qml() -> None:
    ts = _read(_EDITOR_TS)
    implementation = ts.index(
        "loadDocument(payload: LoadDocumentPayload)",
        ts.index("class NovelEditor"),
    )
    load_block = ts[implementation:ts.index("requestSave(): void", implementation)]
    assert "this.reportWordCount()" in load_block


def test_webengine_view_has_explicit_background_color() -> None:
    qml = _read(_WEBVIEW_QML)
    assert "property color editorSurfaceColor: Theme.tokens.color.bgEditor" in qml
    assert "backgroundColor: editorSurfaceColor" in qml


def test_document_load_waits_for_webchannel_editor_ready_and_tracks_chapter_switches() -> None:
    webview = _read(_WEBVIEW_QML)
    writing = _read(_ROOT / "qml" / "pages" / "WritingPage.qml")
    assert "function onDocumentReady()" in webview
    assert "webView.editorLoaded()" in webview
    assert "pendingDocumentPayload" in webview
    assert "documentLoadRetry" in webview
    assert "function flushPendingDocument()" in webview
    assert "if (!window.__novelEditor)" in webview
    assert "LoadSucceededStatus" in webview
    assert "function onChapterChanged()" in writing
    assert "root.lastEditorChapterId !== Facade.currentChapterId" in writing


def test_deterministic_parse_failures_never_retry() -> None:
    """2026-08-26 ticket: only NOT_READY may retry; deterministic failures stop."""
    webview = _read(_WEBVIEW_QML)
    assert "try {" in webview, "page JS must catch parser exceptions"
    assert (
        "JSON.stringify(window.__novelEditor.loadDocument(" in webview
    ), "load result must travel back as JSON"
    assert (
        webview.count("documentLoadRetry.restart()") == 1
    ), "retry timer must be reachable only from the NOT_READY branch"
    restart_at = webview.index("documentLoadRetry.restart()")
    not_ready_at = webview.index('resultJson === undefined || resultJson === null')
    failed_at = webview.index("webView.documentLoadFailed(result.status)")
    assert not_ready_at < restart_at < failed_at, (
        "restart() must live inside the NOT_READY branch, before the "
        "deterministic failure branch that never retries"
    )
    assert "pendingDocumentPayload = \"\"" in webview


def test_failed_chapter_switch_shows_fixed_overlay_instead_of_stale_body() -> None:
    """2026-08-26 ticket: no 'new title + old body' after a failed load."""
    writing = _read(_ROOT / "qml" / "pages" / "WritingPage.qml")
    assert 'objectName: "chapterLoadErrorOverlay"' in writing
    assert "当前章节包含编辑器暂不支持的 Markdown 语法，正文未切换。" in writing
    assert "章节正文加载失败，请重新选择章节。" in writing
    assert "onDocumentLoadFailed: function(reason)" in writing
    assert "onDocumentLoaded: function(chapterId, revision, wordCount)" in writing
    assert "chapterLoadErrorText" in writing


def test_webengine_is_default_and_textarea_is_explicit_fallback() -> None:
    assert _use_webengine_from_args(["ai-novel-studio"]) is True
    assert _use_webengine_from_args(["ai-novel-studio", "--webengine"]) is True
    assert _use_webengine_from_args(["ai-novel-studio", "--textarea"]) is False
    assert (
        _use_webengine_from_args(
            ["ai-novel-studio", "--webengine", "--textarea"]
        )
        is False
    )


def test_qml_scroll_surfaces_use_one_themed_scrollbar() -> None:
    components = _ROOT / "qml" / "components"
    sidebar = _read(components / "ContextSidebar.qml")
    agent = _read(components / "CreativeAgentPanel.qml")
    for source in (sidebar, agent):
        assert "ScrollBar.vertical: AppScrollBar" in source
        assert "ScrollBar.vertical: ScrollBar" not in source
    scrollbar = _read(components / "AppScrollBar.qml")
    assert "import QtQuick.Controls.Basic as Basic" in scrollbar
    assert "Basic.ScrollBar {" in scrollbar
    assert "contentItem: Rectangle" in scrollbar
    assert "Theme.tokens.color.accent" in scrollbar


def test_model_status_uses_reactive_property_not_function_call() -> None:
    app = _read(_APP_QML)
    assert "ModelSettings.modelStatusText()" not in app
    assert "ModelSettings.modelStatusText" in app


def test_agent_dock_geometry_switches_in_one_step() -> None:
    """Ideal-UI spec 10.1: dock and sidebar never animate around WebEngine.

    C1.5 gated the width animation off only in WebEngine mode; the ideal-UI
    spec makes one-step geometry switches the rule for every mode, with the
    panel content fading in/out instead and dragging committing on release.
    """
    dock = _read(_DOCK_QML)
    assert "Behavior on Layout.preferredWidth" not in dock
    assert "panelFadeIn" in dock and "panelFadeOut" in dock
    assert "beginResizeDrag" in dock and "commitResizeDrag" in dock
    assert "agentDragPreview" in dock
    app = _read(_APP_QML)
    assert "animateWidth" not in app
    assert "Behavior on Layout.preferredWidth" not in app
