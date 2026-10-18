"""C1.5: real-display verification for WebEngine black edge strips.

Run with the real Windows platform (never offscreen). Modes:

  --mode cold --out <png>            one cold start: load, wait for the editor
                                     page, grab the window, assert no black
                                     bands around the WebEngine view, save PNG.
  --mode interact [--scale 1.25]     in one process: 20 AI open/close cycles,
                                     20 chapter switches, dock widths
                                     360/420/520; grab + edge-assert each step,
                                     save startup/AI-open/AI-closed PNGs.
  --mode audit [--scale 1.25]        measure how long the AI-close resize
                                     artifact lasts across 10 cycles and fail
                                     if it ever persists beyond 150ms.

The edge assertion scans the four 4px bands around the WebEngine view plus
full-width column/row runs for near-black pixels (QtWebEngine's default canvas
is pure black); any band above the threshold fails with a non-zero exit.

Interact mode pumps ~60ms after each toggle before asserting: the C1.5 resize
nudge needs one renderer round-trip to land. The audit mode separately proves
the artifact never persists (it clears in a few frames instead of hanging).
"""

from __future__ import annotations

import argparse
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from PySide6.QtCore import QPointF, QUrl  # noqa: E402
from PySide6.QtGui import QGuiApplication, QImage  # noqa: E402
from PySide6.QtQml import QQmlApplicationEngine  # noqa: E402
from PySide6.QtQuick import QQuickItem, QQuickWindow  # noqa: E402

from ai_novel_studio.ui_qml.bootstrap import (  # noqa: E402
    EditorAssets,
    app_qml_path,
    register_frontend_types,
)
from ai_novel_studio.ui_qml.editor_runtime import (  # noqa: E402
    ensure_editor_dist,
    ensure_qwebchannel_js,
)

_BLACK_LUMA = 24
_BAND = 4
_BAND_FAIL_FRACTION = 0.4
_RUN_FAIL_FRACTION = 0.7
_OUT_DIR = (
    Path(__file__).resolve().parent.parent / "docs" / "frontend" / "screenshots"
)


def _find_all(root: QQuickItem, name: str) -> list[QQuickItem]:
    matches: list[QQuickItem] = []
    if root.objectName() == name:
        matches.append(root)
    for child in root.childItems():
        matches.extend(_find_all(child, name))
    return matches


def _luma(pixel: int) -> int:
    red = (pixel >> 16) & 0xFF
    green = (pixel >> 8) & 0xFF
    blue = pixel & 0xFF
    return int(0.2126 * red + 0.7152 * green + 0.0722 * blue)


def _band_black_fraction(image: QImage, x0: int, y0: int, w: int, h: int) -> float:
    dark = 0
    total = 0
    for y in range(y0, min(y0 + h, image.height())):
        for x in range(x0, min(x0 + w, image.width())):
            total += 1
            if _luma(image.pixel(x, y)) < _BLACK_LUMA:
                dark += 1
    return dark / total if total else 0.0


def _assert_no_black_edges(
    image: QImage,
    view: QQuickItem,
    label: str,
) -> None:
    """Assert the WebEngine view has no black band on any of its four edges."""
    device_scale = image.devicePixelRatio()
    origin = view.mapToScene(QPointF(0, 0))
    x0 = max(0, int(origin.x() * device_scale))
    y0 = max(0, int(origin.y() * device_scale))
    w = int(view.width() * device_scale)
    h = int(view.height() * device_scale)
    bands = {
        "top": (x0, y0, w, _BAND),
        "bottom": (x0, y0 + h - _BAND, w, _BAND),
        "left": (x0, y0, _BAND, h),
        "right": (x0 + w - _BAND, y0, _BAND, h),
    }
    for name, (bx, by, bw, bh) in bands.items():
        fraction = _band_black_fraction(image, bx, by, bw, bh)
        if fraction > _BAND_FAIL_FRACTION:
            raise AssertionError(
                f"{label}: black {name} band fraction {fraction:.2f} "
                f"at ({bx},{by}) {bw}x{bh}"
            )

    # L-shape scan: look for solid near-black columns/rows across the middle
    # region (a black strip renders as a nearly solid run, text never does).
    region_x0 = max(x0 + 40, 0)
    region_x1 = min(x0 + w - 40, image.width())
    region_y0 = max(y0 + 40, 0)
    region_y1 = min(y0 + h - 40, image.height())
    for column in range(region_x0, region_x1):
        dark = sum(
            1
            for y in range(region_y0, region_y1)
            if _luma(image.pixel(column, y)) < _BLACK_LUMA
        )
        total = region_y1 - region_y0
        if total and dark / total > _RUN_FAIL_FRACTION:
            raise AssertionError(
                f"{label}: near-solid black column at x={column} "
                f"({dark}/{total})"
            )
    for row in range(region_y0, region_y1):
        dark = sum(
            1
            for x in range(region_x0, region_x1)
            if _luma(image.pixel(x, row)) < _BLACK_LUMA
        )
        total = region_x1 - region_x0
        if total and dark / total > _RUN_FAIL_FRACTION:
            raise AssertionError(
                f"{label}: near-solid black row at y={row} ({dark}/{total})"
            )


def _wait_for_editor(app: QGuiApplication, webview: QQuickItem, timeout: float) -> bool:
    """Wait for the QML `editorLoaded` signal (fires on page load success)."""
    ready = False

    def set_ready() -> None:
        nonlocal ready
        ready = True

    webview.editorLoaded.connect(set_ready)
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        for _ in range(30):
            app.processEvents()
        if ready:
            return True
        time.sleep(0.05)
    return False


def _grab_and_check(
    app: QGuiApplication,
    window: QQuickWindow,
    webview: QQuickItem,
    label: str,
    path: Path | None = None,
    settle_ms: int = 0,
) -> None:
    if settle_ms:
        deadline = time.monotonic() + settle_ms / 1000
        while time.monotonic() < deadline:
            app.processEvents()
            time.sleep(0.01)
    for _ in range(12):
        app.processEvents()
    image = window.grabWindow()
    try:
        _assert_no_black_edges(image, webview, label)
    except AssertionError:
        _OUT_DIR.mkdir(parents=True, exist_ok=True)
        image.save(str(_OUT_DIR / "c1.5-fail-frame.png"))
        print(f"  saved exact failing frame c1.5-fail-frame.png ({label})")
        raise
    if path is not None:
        _OUT_DIR.mkdir(parents=True, exist_ok=True)
        if not image.save(str(path)):
            raise AssertionError(f"failed to save {path.name}")
        print(f"  saved {path.name}")


def _build_engine(app: QGuiApplication) -> tuple[QQmlApplicationEngine, object, QQuickWindow]:
    # Mirror the production bootstrap: software compositing avoids the GPU
    # context-loss black strips during dock resize.
    os.environ.setdefault("QTWEBENGINE_CHROMIUM_FLAGS", "--disable-gpu")
    ensure_editor_dist()
    ensure_qwebchannel_js()
    from PySide6.QtWebEngineQuick import QtWebEngineQuick

    QtWebEngineQuick.initialize()
    engine = QQmlApplicationEngine()
    engine.addImportPath(str(Path(app_qml_path()).parent))
    facade, _ = register_frontend_types(engine)
    engine.rootContext().setContextProperty("WritingPageUseWebEngine", True)

    from ai_novel_studio.ui_qml.bridge.editor_bridge import EditorBridge

    editor_bridge = EditorBridge(engine)
    editor_bridge.save_requested.connect(
        lambda chapter_id, revision, markdown, content_hash: facade.saveFromEditor(
            chapter_id, revision, markdown
        )
    )
    editor_bridge.error.connect(facade.setSaveStatusText)
    editor_bridge.word_count_changed.connect(facade.setWebEngineWordCount)
    editor_bridge.selection_reference_changed.connect(facade.setSelectionReferenceJson)
    engine.rootContext().setContextProperty("pythonBridge", editor_bridge)
    dist = ensure_editor_dist()
    engine.rootContext().setContextProperty(
        "EditorAssets",
        EditorAssets((dist / "index.html").as_uri(), engine),
    )
    engine.load(QUrl.fromLocalFile(str(app_qml_path())))
    assert engine.rootObjects(), "App.qml failed to load with WebEngine"
    root = engine.rootObjects()[0]
    root.show()
    windows = [w for w in app.topLevelWindows() if isinstance(w, QQuickWindow)]
    assert windows, "no QQuickWindow"
    return engine, facade, windows[0]


def _find_webview(content: QQuickItem) -> QQuickItem:
    matches = _find_all(content, "novelEditorView")
    visible = [item for item in matches if item.isVisible()]
    assert visible, "NovelEditorView not found/visible"
    return visible[0]


def _run_cold(args: argparse.Namespace) -> int:
    app = QGuiApplication([])
    engine, facade, window = _build_engine(app)
    content = window.contentItem()
    webview = _find_webview(content)
    if not _wait_for_editor(app, webview, timeout=20.0):
        print(f"FAIL cold: editor did not become ready ({args.out})")
        return 1
    for _ in range(30):
        app.processEvents()
    try:
        _grab_and_check(
            app,
            window,
            webview,
            f"cold {args.out.name}",
            Path(args.out),
        )
    except AssertionError as exc:
        print(f"FAIL cold: {exc}")
        return 1
    print(f"OK   cold {args.out.name}")
    return 0


def _run_interact(args: argparse.Namespace) -> int:
    app = QGuiApplication([])
    engine, facade, window = _build_engine(app)
    content = window.contentItem()
    webview = _find_webview(content)
    if not _wait_for_editor(app, webview, timeout=20.0):
        print("FAIL interact: editor did not become ready")
        return 1
    for _ in range(30):
        app.processEvents()

    # Startup screenshot + edge assertion.
    _grab_and_check(
        app,
        window,
        webview,
        "startup",
        _OUT_DIR / "c1.5-startup.png",
    )

    # 20 AI open/close cycles, asserting edges on every frame.
    for index in range(20):
        for open_state, label in ((True, f"ai-open-{index}"), (False, f"ai-closed-{index}")):
            facade.toggleAiDrawer(open_state)
            path = (
                _OUT_DIR / "c1.5-ai-open.png"
                if open_state and index == 0
                else _OUT_DIR / "c1.5-ai-closed.png"
                if not open_state and index == 0
                else None
            )
            try:
                _grab_and_check(
                    app,
                    window,
                    webview,
                    label,
                    path,
                    settle_ms=60,
                )
            except AssertionError:
                raise

    # Dock widths 360/420/520 while open.
    facade.toggleAiDrawer(True)
    dock = _find_all(content, "agentDock")[0]
    for width in (360, 420, 520):
        dock.setProperty("currentWidth", width)
        for _ in range(12):
            app.processEvents()
        _grab_and_check(
            app,
            window,
            webview,
            f"dock-{width}px",
            _OUT_DIR / f"c1.5-dock-{width}px.png",
        )

    # 20 chapter switches (skip volume header rows).
    chapter_rows = (1, 2, 3, 5, 6)
    for index in range(20):
        facade.selectChapter(chapter_rows[index % len(chapter_rows)])
        for _ in range(16):
            app.processEvents()
        time.sleep(0.05)
        _grab_and_check(app, window, webview, f"chapter-{index}")

    print(f"OK   interact scale={args.scale}")
    return 0


def _run_audit(args: argparse.Namespace) -> int:
    """Measure the max persistence of the AI-close resize artifact."""
    app = QGuiApplication([])
    engine, facade, window = _build_engine(app)
    content = window.contentItem()
    webview = _find_webview(content)
    if not _wait_for_editor(app, webview, timeout=20.0):
        print("FAIL audit: editor did not become ready")
        return 1
    for _ in range(30):
        app.processEvents()

    facade.toggleAiDrawer(True)
    for _ in range(20):
        app.processEvents()
    im0 = window.grabWindow()
    old_right = int(
        (webview.mapToScene(QPointF(0, 0)).x() + webview.width())
        * im0.devicePixelRatio()
    )
    facade.toggleAiDrawer(False)
    for _ in range(8):
        app.processEvents()
    im1 = window.grabWindow()
    new_right = int(
        (webview.mapToScene(QPointF(0, 0)).x() + webview.width())
        * im1.devicePixelRatio()
    )
    print(f"  strip region device x: {old_right}..{new_right}")

    max_clear = 0.0
    for cycle in range(10):
        facade.toggleAiDrawer(True)
        for _ in range(10):
            app.processEvents()
        facade.toggleAiDrawer(False)
        started = time.monotonic()
        seen = False
        cleared_at: float | None = None
        for _ in range(12):
            image = window.grabWindow()
            fraction = _strip_black_fraction(
                image,
                webview,
                old_right,
                new_right,
            )
            now = time.monotonic() - started
            if fraction > 0.5:
                seen = True
            elif seen and cleared_at is None:
                cleared_at = now
            time.sleep(0.02)
        if seen:
            persist = cleared_at if cleared_at is not None else 1.0
            max_clear = max(max_clear, persist)
            print(f"  cycle {cycle}: artifact seen, cleared after {persist:.3f}s")

    if max_clear > 0.15:
        print(f"FAIL audit: artifact persisted {max_clear:.3f}s (>150ms)")
        return 1
    print(f"OK   audit scale={args.scale} max_persistence={max_clear:.3f}s")
    return 0


def _strip_black_fraction(
    image: QImage,
    view: QQuickItem,
    x_from: int,
    x_to: int,
) -> float:
    device_scale = image.devicePixelRatio()
    origin = view.mapToScene(QPointF(0, 0))
    y0 = int(origin.y() * device_scale)
    height = int(view.height() * device_scale)
    dark = 0
    total = 0
    for x in range(x_from, x_to):
        for y in range(y0, y0 + height, 8):
            total += 1
            if _luma(image.pixel(x, y)) < _BLACK_LUMA:
                dark += 1
    return dark / total if total else 0.0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=("cold", "interact", "audit"), required=True)
    parser.add_argument("--out", type=Path, default=None)
    parser.add_argument("--scale", type=float, default=1.0)
    args = parser.parse_args()

    os.environ["QT_SCALE_FACTOR"] = str(args.scale)
    if args.mode == "cold":
        assert args.out is not None, "--out is required for cold mode"
        return _run_cold(args)
    if args.mode == "audit":
        return _run_audit(args)
    return _run_interact(args)


if __name__ == "__main__":
    raise SystemExit(main())
