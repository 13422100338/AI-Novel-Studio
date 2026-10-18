"""Capture Native Glass Lab states (offscreen by default, windowed optional).

Usage (from the worktree root, using its venv):
    .\\.venv\\Scripts\\python.exe scripts\\capture_native_glass_lab.py
    .\\.venv\\Scripts\\python.exe scripts\\capture_native_glass_lab.py --windowed

Offscreen mode:
    QT_QPA_PLATFORM=offscreen + software backend + FakeNativeGlassBridge
    (apply() always False; DWM cannot run offscreen). Saves root.grabWindow()
    for the six states and applies the "no pure-black block" assertion used by
    tests/ui_qml/test_visual_lab.py.

Windowed mode:
    Real NativeGlassBridge + frameless transparent window. Waits ~1s after
    show for DWM to settle, then for every state saves:
      - root.grabWindow() (app content only; does NOT claim DWM material);
      - PrintWindow(PW_RENDERFULLCONTENT) as the DWM composition evidence
        (native-glass-lab-{state}-composed.png). QScreen.grabWindow(0) is
        deliberately NOT used: on this machine it captures whatever covers
        the window (a fullscreen game), not the frameless transparent lab
        window. No pixel assertions: output depends on GPU/wallpaper/DPI.
    Optional --stripes: when scripts/stripe_backdrop_window.py was started
    first, the lab is raised above the stripe window so Desktop Acrylic can
    sample it (deterministic blur-through evidence; see the experiment doc).
    If the windowed capture cannot run (e.g. headless), prints a clear error
    and exits non-zero.

    Outputs (docs/frontend/screenshots/):
    native-glass-lab-{state}.png           app content (both modes)
    native-glass-lab-{state}-composed.png  PrintWindow DWM composition evidence
"""

from __future__ import annotations

import os
import sys
import time
from pathlib import Path

_WINDOWED = "--windowed" in sys.argv
if not _WINDOWED:
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
if not _WINDOWED:
    # Offscreen runs use the software rasterizer for deterministic pixels.
    # Windowed runs keep the real hardware backend so the DWM composition
    # evidence reflects the actual machine (software would mask GPU quirks).
    os.environ.setdefault("QT_QUICK_BACKEND", "software")
os.environ.setdefault("QT_QUICK_CONTROLS_STYLE", "Basic")

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from PySide6.QtCore import (  # noqa: E402
    Property,
    QMetaObject,
    QObject,
    QUrl,
    Signal,
    Slot,
)
from PySide6.QtGui import QGuiApplication, QImage  # noqa: E402
from PySide6.QtQml import QQmlApplicationEngine  # noqa: E402
from PySide6.QtQuick import QQuickItem, QQuickWindow  # noqa: E402

from ai_novel_studio.ui_qml.bootstrap import (  # noqa: E402
    NativeGlassBridge,
    native_glass_lab_qml_path,
    register_frontend_types,
)

OUT_DIR = (
    Path(__file__).resolve().parent.parent
    / "docs"
    / "frontend"
    / "screenshots"
)

_STATES = (
    ("native-acrylic-dark", "native", "acrylic", "dark"),
    ("native-mica-dark", "native", "mica", "dark"),
    ("internal-dark", "internal", "acrylic", "dark"),
    ("solid-dark", "solid", "acrylic", "dark"),
    ("native-acrylic-light", "native", "acrylic", "light"),
    ("solid-light", "solid", "acrylic", "light"),
)


class FakeNativeGlassBridge(QObject):
    """Offscreen stand-in: same surface as ``NativeGlassBridge``, apply fails."""

    capabilitiesChanged = Signal()

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self.apply_result = False
        self.calls: list[str] = []
        self.dark_mode_calls: list[bool] = []
        self.refresh_calls = 0
        self._active_kind = "none"

    @Property(str, constant=True)
    def platformName(self) -> str:
        return "offscreen-fake"

    @Property(str, constant=True)
    def buildText(self) -> str:
        return "-"

    @Property(bool, constant=True)
    def nativeSupported(self) -> bool:
        return True

    @Property(bool, constant=True)
    def transparencyEffects(self) -> bool:
        return False

    @Property(str, constant=True)
    def unsupportedReason(self) -> str:
        return "offscreen fake bridge"

    @Property(str, notify=capabilitiesChanged)
    def activeKind(self) -> str:
        return self._active_kind

    @Property(bool, notify=capabilitiesChanged)
    def nativeActive(self) -> bool:
        return self._active_kind != "none"

    @Slot(str, result=bool)
    def apply(self, kind: str) -> bool:
        self.calls.append(kind)
        if kind == "none":
            self._active_kind = "none"
            self.capabilitiesChanged.emit()
            return False
        self._active_kind = kind if self.apply_result else "none"
        self.capabilitiesChanged.emit()
        return self.apply_result

    @Slot(bool, result=bool)
    def setDarkMode(self, enabled: bool) -> bool:
        self.dark_mode_calls.append(enabled)
        return True

    @Slot(result=bool)
    def refresh(self) -> bool:
        self.refresh_calls += 1
        return False


def _pump(app: QGuiApplication, rounds: int = 8) -> None:
    for _ in range(rounds):
        app.processEvents()
        time.sleep(0.03)


def _find_item(root: QQuickItem, name: str) -> QQuickItem | None:
    if root.objectName() == name:
        return root
    for child in root.childItems():
        found = _find_item(child, name)
        if found is not None:
            return found
    return None


def _click(window: QQuickWindow, name: str) -> None:
    item = _find_item(window.contentItem(), name)
    assert item is not None, f"missing control {name}"
    QMetaObject.invokeMethod(item, "clicked")


def _backdrop_covers(window: QQuickWindow) -> bool:
    backdrop = _find_item(window.contentItem(), "ngBackdrop")
    if backdrop is None:
        return False
    return (
        backdrop.x() == 0
        and backdrop.y() == 0
        and abs(backdrop.width() - float(window.width())) < 1
        and abs(backdrop.height() - float(window.height())) < 1
    )


def _assert_clean_window(window: QQuickWindow, image: QImage, label: str) -> None:
    """Diagnosis-13 rule: no pure-black sampled pixels in the app content."""
    assert _backdrop_covers(window), f"{label}: ngBackdrop never covered window"
    dark = 0
    for y in range(0, image.height(), 8):
        for x in range(0, image.width(), 8):
            c = image.pixelColor(x, y)
            if max(c.red(), c.green(), c.blue()) < 12:
                dark += 1
    assert dark == 0, f"{label}: {dark} pure-black sampled pixels"


def _set_theme(
    app: QGuiApplication,
    window: QQuickWindow,
    theme_provider: object,
    desired: str,
) -> None:
    """Toggle ngThemeButton (bounded) until QML and ThemeProvider agree."""
    for _ in range(4):
        if (
            window.property("themeName") == desired
            and theme_provider.property("themeName") == desired  # type: ignore[attr-defined]
        ):
            return
        _click(window, "ngThemeButton")
        _pump(app, 6)
    raise RuntimeError(f"could not reach theme {desired}")


def _set_mode(app: QGuiApplication, window: QQuickWindow, mode: str) -> None:
    if window.property("mode") == mode:
        return
    button = {
        "native": "ngModeNative",
        "internal": "ngModeInternal",
        "solid": "ngModeSolid",
    }[mode]
    _click(window, button)
    _pump(app, 8)
    if window.property("mode") != mode:
        raise RuntimeError(f"could not switch mode to {mode}")


def _set_kind(app: QGuiApplication, window: QQuickWindow, kind: str) -> None:
    if window.property("nativeKind") == kind:
        return
    _click(window, "ngMicaButton" if kind == "mica" else "ngAcrylicButton")
    _pump(app, 8)
    if window.property("nativeKind") != kind:
        raise RuntimeError(f"could not switch native kind to {kind}")


def _capture_app_content(window: QQuickWindow) -> QImage:
    for _ in range(6):
        window.contentItem().update()
    image = window.grabWindow()
    assert not image.isNull(), "grabWindow returned a null image"
    return image


def _capture_screen_composed(
    window: QQuickWindow,
) -> QImage | None:
    """Grab the real screen composition covering this window (DPR-corrected).

    Unlike PrintWindow, this includes the DWM blur layer over the desktop.
    It is only valid while the window is actually visible on the desktop
    (a fullscreen exclusive game covering it makes the evidence useless,
    verified on this machine on 2026-08-06).
    """
    screen = window.screen()
    if screen is None:
        screen = QGuiApplication.primaryScreen()
    if screen is None:
        return None
    image = screen.grabWindow(0).toImage()
    if image.isNull():
        return None
    dpr = float(screen.devicePixelRatio())
    geo = window.geometry()
    screen_geo = screen.geometry()
    x = round((geo.x() - screen_geo.x()) * dpr)
    y = round((geo.y() - screen_geo.y()) * dpr)
    width = round(geo.width() * dpr)
    height = round(geo.height() * dpr)
    x = max(0, min(x, image.width() - 1))
    y = max(0, min(y, image.height() - 1))
    width = max(1, min(width, image.width() - x))
    height = max(1, min(height, image.height() - y))
    crop = image.copy(x, y, width, height)
    if crop.isNull():
        return None
    return crop


def _print_background_strip_stats(image: QImage, label: str) -> None:
    """Stats for a pure-wash strip inside the 40px custom title bar.

    The middle of the title bar (between the title text and the window
    buttons) contains only the window wash over the DWM backdrop: no panels,
    no text, no scrollbars. Texture there (blurred stripes/wallpaper) means
    the DWM material is really sampling the desktop.
    """
    if image.isNull():
        print(f"  {label}: stats skipped (null image)")
        return
    # Title bar is the top 40 logical px; sample its middle band (logical
    # y 12..30) and the horizontal gap between the labels and the buttons
    # (logical x 30%..62%).
    y0 = round(image.height() * 0.015)
    y1 = round(image.height() * 0.037)
    x0 = round(image.width() * 0.30)
    x1 = round(image.width() * 0.62)
    colors: set[tuple[int, int, int]] = set()
    rs: list[int] = []
    gs: list[int] = []
    bs: list[int] = []
    for y in range(y0, y1):
        for x in range(x0, x1):
            c = image.pixelColor(x, y)
            colors.add((c.red(), c.green(), c.blue()))
            rs.append(c.red())
            gs.append(c.green())
            bs.append(c.blue())
    import statistics

    print(
        f"  {label}: unique={len(colors)} "
        f"mean=({statistics.fmean(rs):.0f},{statistics.fmean(gs):.0f},"
        f"{statistics.fmean(bs):.0f}) "
        f"std=({statistics.pstdev(rs):.1f},{statistics.pstdev(gs):.1f},"
        f"{statistics.pstdev(bs):.1f})"
    )


def _make_topmost(window: QQuickWindow) -> None:
    """Raise the lab above the striped backdrop window (Z-order for DWM).

    The stripe window is started first as a topmost full-screen window. The
    lab is then made topmost too, so DWM's Desktop Acrylic samples the stripe
    window (not the fullscreen game underneath). Best-effort, no-op on
    non-Windows or when the handle is not ready.
    """
    if os.name != "nt":
        return
    import ctypes

    try:
        hwnd = ctypes.wintypes.HWND(int(window.winId()))
    except (AttributeError, TypeError, ValueError):
        return
    user32 = ctypes.WinDLL("user32")
    # HWND_TOPMOST = -1; SWP_NOSIZE|SWP_NOMOVE|SWP_NOACTIVATE = 1|2|0x10
    user32.SetWindowPos(
        hwnd, ctypes.wintypes.HWND(-1), 0, 0, 0, 0,
        0x0001 | 0x0002 | 0x0010,
    )


def _capture_print_window(window: QQuickWindow) -> QImage | None:
    """Capture the window's DWM-composited content via PrintWindow.

    QScreen.grabWindow(0) shows whatever covers the window (verified on this
    machine: a fullscreen game produced garbage evidence). PrintWindow with
    PW_RENDERFULLCONTENT asks DWM to render THIS window's composed surface,
    including the system backdrop, even when another window is in front.
    Returns None when the API is unavailable or fails.
    """
    if os.name != "nt":
        return None
    import ctypes
    from ctypes import wintypes

    class BITMAPINFOHEADER(ctypes.Structure):
        _fields_ = [
            ("biSize", wintypes.DWORD),
            ("biWidth", wintypes.LONG),
            ("biHeight", wintypes.LONG),
            ("biPlanes", wintypes.WORD),
            ("biBitCount", wintypes.WORD),
            ("biCompression", wintypes.DWORD),
            ("biSizeImage", wintypes.DWORD),
            ("biXPelsPerMeter", wintypes.LONG),
            ("biYPelsPerMeter", wintypes.LONG),
            ("biClrUsed", wintypes.DWORD),
            ("biClrImportant", wintypes.DWORD),
        ]

    user32 = ctypes.WinDLL("user32")
    gdi32 = ctypes.WinDLL("gdi32")
    try:
        hwnd = wintypes.HWND(int(window.winId()))
    except (AttributeError, TypeError, ValueError):
        return None
    rect = wintypes.RECT()
    if not user32.GetWindowRect(hwnd, ctypes.byref(rect)):
        return None
    width = int(rect.right - rect.left)
    height = int(rect.bottom - rect.top)
    if width <= 0 or height <= 0:
        return None
    hdc_win = user32.GetWindowDC(hwnd)
    if not hdc_win:
        return None
    hdc_mem = None
    hbmp = None
    try:
        hdc_mem = gdi32.CreateCompatibleDC(hdc_win)
        hbmp = gdi32.CreateCompatibleBitmap(hdc_win, width, height)
        if not hdc_mem or not hbmp:
            return None
        gdi32.SelectObject(hdc_mem, hbmp)
        # PW_RENDERFULLCONTENT = 0x00000002
        ok = bool(user32.PrintWindow(hwnd, hdc_mem, 2))
        if not ok:
            return None
        stride = width * 4
        buf = ctypes.create_string_buffer(stride * height)
        bmi = BITMAPINFOHEADER()
        bmi.biSize = ctypes.sizeof(BITMAPINFOHEADER)
        bmi.biWidth = width
        bmi.biHeight = -height  # top-down rows
        bmi.biPlanes = 1
        bmi.biBitCount = 32
        bmi.biCompression = 0  # BI_RGB
        got = gdi32.GetDIBits(
            hdc_mem,
            hbmp,
            0,
            height,
            buf,
            ctypes.byref(bmi),
            0,  # DIB_RGB_COLORS
        )
        if got != height:
            return None
        image = QImage(
            bytes(buf),
            width,
            height,
            stride,
            QImage.Format.Format_ARGB32,
        )
        return image.copy()
    finally:
        if hbmp is not None:
            gdi32.DeleteObject(hbmp)
        if hdc_mem is not None:
            gdi32.DeleteDC(hdc_mem)
        user32.ReleaseDC(hwnd, hdc_win)


def main() -> int:
    try:
        app = QGuiApplication(sys.argv)
        engine = QQmlApplicationEngine()
        engine.addImportPath(str(Path(native_glass_lab_qml_path()).parent))
        _, theme = register_frontend_types(engine)
        if _WINDOWED:
            # Frameless transparent windows need an alpha swapchain before the
            # first QQuickWindow is created (same as bootstrap.main).
            QQuickWindow.setDefaultAlphaBuffer(True)
            bridge: QObject | NativeGlassBridge = NativeGlassBridge(engine)
        else:
            bridge = FakeNativeGlassBridge()
        engine.rootContext().setContextProperty("NativeGlassBridge", bridge)
        engine.rootContext().setContextProperty(
            "RenderBackendInfo", QQuickWindow.sceneGraphBackend() or "unknown"
        )
        engine.load(QUrl.fromLocalFile(str(native_glass_lab_qml_path())))
        if not engine.rootObjects():
            raise RuntimeError("NativeGlassLab.qml failed to load")
        root = engine.rootObjects()[0]
        assert isinstance(root, QQuickWindow), "Native Glass Lab window expected"
        if _WINDOWED:
            assert isinstance(bridge, NativeGlassBridge)
            bridge.setWindow(root)
            # Bring the lab to the foreground: DWM can reject the system
            # backdrop while the window is not active (verified 2026-08-06),
            # and QScreen.grabWindow(0) only shows the window when nothing
            # else covers it.
            root.raise_()
            root.requestActivate()
        root.show()
        if _WINDOWED:
            _pump(app, 8)
            time.sleep(1.0)  # let DWM settle after the first show
            root.raise_()
            root.requestActivate()
            _make_topmost(root)
            _pump(app, 8)
            _pump(app, 8)
        else:
            _pump(app, 12)
        OUT_DIR.mkdir(parents=True, exist_ok=True)
        print(
            f"platform={'windowed' if _WINDOWED else 'offscreen'} "
            f"backend={QQuickWindow.sceneGraphBackend() or 'unknown'} "
            f"window={root.width()}x{root.height()}"
        )

        for stem, mode, kind, theme_name in _STATES:
            _set_theme(app, root, theme, theme_name)
            _set_mode(app, root, mode)
            _set_kind(app, root, kind)
            if _WINDOWED and mode == "native":
                # Wait (bounded) for the DWM attribute to actually stick;
                # the QML retry timer re-applies on activation, so this also
                # covers the first-call race seen on 25H2.
                for _ in range(30):
                    if bool(root.property("nativeActive")):
                        break
                    root.raise_()
                    root.requestActivate()
                    _pump(app, 4)
                    time.sleep(0.15)
                active = bool(root.property("nativeActive"))
                print(
                    "  nativeActive=" + str(active)
                    + (" (reached after retry loop)" if active else " (still inactive)")
                )
            if _WINDOWED:
                _pump(app, 8)
                time.sleep(0.4)  # DWM re-settle after mode/kind changes
            else:
                _pump(app, 10)
            for _ in range(30):
                if _backdrop_covers(root):
                    break
                _pump(app, 1)
            assert _backdrop_covers(root), f"{stem}: backdrop never covered window"

            image = _capture_app_content(root)
            if not _WINDOWED:
                _assert_clean_window(root, image, stem)
            path = OUT_DIR / f"native-glass-lab-{stem}.png"
            assert image.save(str(path)), f"failed to save {path}"
            print(f"saved {path}")

            if _WINDOWED:
                # PrintWindow(PW_RENDERFULLCONTENT) asks DWM to compose THIS
                # window's surface, so the evidence survives another window
                # covering the desktop (fullscreen game verified on this
                # machine). QScreen.grabWindow(0) is NOT used: on this machine
                # it captures whatever covers the window (a fullscreen game),
                # not the frameless transparent lab window.
                composed = _capture_print_window(root)
                if composed is not None and not composed.isNull():
                    composed_path = (
                        OUT_DIR / f"native-glass-lab-{stem}-composed.png"
                    )
                    assert composed.save(str(composed_path)), (
                        f"failed to save {composed_path}"
                    )
                    print(f"  composed evidence: {composed_path}")
                else:
                    print("  composed evidence: unavailable (PrintWindow failed)")

                # Real screen composition (includes the DWM blur layer over
                # the desktop). Valid now that no fullscreen game is covering
                # the desktop; stats reveal whether the wallpaper texture is
                # actually blurred into the window background.
                screen_composed = _capture_screen_composed(root)
                if screen_composed is not None and not screen_composed.isNull():
                    screen_path = OUT_DIR / f"native-glass-lab-{stem}-screen.png"
                    assert screen_composed.save(str(screen_path)), (
                        f"failed to save {screen_path}"
                    )
                    _print_background_strip_stats(screen_composed, stem)
                else:
                    print(
                        "  screen evidence: unavailable "
                        "(QScreen.grabWindow(0) failed)"
                    )
        engine.deleteLater()
        return 0
    except Exception as exc:
        print(f"capture_native_glass_lab failed: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
