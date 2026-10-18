"""Windows 11 system backdrop (Mica / Desktop Acrylic) for frontend labs.

Consumed by the standalone ``--native-glass-lab`` experiment (isolation ticket:
AI-Novel-Studio-原生毛玻璃测试界面-实施任务.md) and by the Visual V0 lab's
optional Mica toggle. ideal-UI spec 12: system material is an optional
enhancement; the app must render correctly without it. The production shell
keeps its opaque, WebEngine-safe background until the native route is
accepted; every failure path here returns ``False``/``"none"`` so the caller
renders a normal opaque window.

The DWM-drawn backdrop (wallpaper blur behind the whole window) is requested
with ``DwmSetWindowAttribute(DWMWA_SYSTEMBACKDROP_TYPE)``:

- ``DWMSBT_MAINWINDOW (2)``       -> Mica
- ``DWMSBT_TRANSIENTWINDOW (3)``  -> Desktop Acrylic (brighter)
- ``DWMSBT_TABBEDWINDOW (4)``     -> Mica Alt

Requires Windows 11 build 22621+; every failure path returns ``False`` so the
caller renders a normal opaque window.
"""

from __future__ import annotations

import ctypes
import os
import sys
from ctypes import wintypes
from typing import Any

# dwmapi.h: DwmSetWindowAttribute attribute id for DWM_SYSTEMBACKDROP_TYPE.
_DWMWA_SYSTEMBACKDROP_TYPE = 38
_DWMWA_USE_IMMERSIVE_DARK_MODE = 20
_DWMWA_USE_IMMERSIVE_DARK_MODE_BEFORE_20H1 = 19
# Windows 11 24H2+ (build 26100+) redirection-bitmap alpha. Some Qt backends
# redraw through a DWM redirection bitmap that treats alpha as opaque unless
# this attribute is requested; without it the system backdrop is composed as
# fully opaque. Unknown attributes are rejected harmlessly on older builds.
_DWMWA_REDIRECTIONBITMAP_ALPHA = 39
_REDIRECTION_BITMAP_MIN_BUILD = 26100

DWMSBT_MAINWINDOW = 2
DWMSBT_TRANSIENTWINDOW = 3
DWMSBT_TABBEDWINDOW = 4
DWMSBT_NONE = 1

# Windows 11 22H2 (first build with the documented system-backdrop enum).
_MIN_BUILD = 22621

_TRANSPARENCY_REGISTRY_KEY = (
    r"SOFTWARE\Microsoft\Windows\CurrentVersion\Themes\Personalize"
)

_BACKDROP_KINDS = {
    "none": DWMSBT_NONE,
    "mica": DWMSBT_MAINWINDOW,
    "acrylic": DWMSBT_TRANSIENTWINDOW,
    "mica-alt": DWMSBT_TABBEDWINDOW,
}


def windows_build() -> int:
    """Return the current Windows build number, or 0 on non-Windows."""
    if os.name != "nt":
        return 0
    version_getter = getattr(sys, "getwindowsversion", None)
    if version_getter is None:
        return 0
    try:
        return int(version_getter().build)
    except (AttributeError, OSError, TypeError, ValueError):
        return 0


def _dwm_set_int(hwnd: int, attribute: int, value: int) -> bool:
    """Call DwmSetWindowAttribute with an int payload; False on failure."""
    try:
        library_factory = getattr(ctypes, "WinDLL", None)
        if library_factory is None:
            return False
        dwmapi = library_factory("dwmapi")
        setter = dwmapi.DwmSetWindowAttribute
        setter.restype = ctypes.c_long
        setter.argtypes = [
            wintypes.HWND,
            ctypes.c_uint,
            wintypes.LPVOID,
            ctypes.c_uint,
        ]
        attr = ctypes.c_uint(attribute)
        payload = ctypes.c_int(value)
        result = setter(
            wintypes.HWND(int(hwnd)),
            attr,
            ctypes.byref(payload),
            ctypes.sizeof(payload),
        )
        return int(result) == 0
    except (AttributeError, OSError, TypeError, ValueError):
        return False


def _dwm_set_backdrop(hwnd: int, backdrop_type: int) -> bool:
    """Call DwmSetWindowAttribute(DWMWA_SYSTEMBACKDROP_TYPE)."""
    return _dwm_set_int(hwnd, _DWMWA_SYSTEMBACKDROP_TYPE, backdrop_type)


def transparency_effects_enabled() -> bool:
    """Read the system "Transparency effects" setting (registry).

    When this is disabled, DWM materials fall back to solid theme colors, so
    the lab reports the native route as unavailable instead of showing a gray
    window that pretends to be glass.
    """
    if os.name != "nt":
        return False
    try:
        import winreg

        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, _TRANSPARENCY_REGISTRY_KEY) as key:
            value, _ = winreg.QueryValueEx(key, "EnableTransparency")
            return bool(value)
    except OSError:
        return False


def supports_system_backdrop() -> bool:
    """True when this machine can ask DWM for a system backdrop."""
    return os.name == "nt" and windows_build() >= _MIN_BUILD


def why_not_available() -> str:
    """Human-readable reason the native route is unavailable (for the lab)."""
    if os.name != "nt":
        return "非 Windows 平台"
    build = windows_build()
    if build < _MIN_BUILD:
        return f"Windows 版本过低（build {build}，需要 22621+）"
    if not transparency_effects_enabled():
        return "系统“透明效果”已关闭，DWM 材质会退化为纯色"
    return "DWM 调用失败"


def effective_backdrop_kind(requested: str) -> str:
    """Resolve a requested kind against the real machine capabilities.

    Returns ``"none"`` when the request cannot honestly be honored, so the
    lab never claims a material is active when Windows would render a flat
    fallback instead.
    """
    if requested == "none" or requested not in _BACKDROP_KINDS:
        return "none"
    if not supports_system_backdrop() or not transparency_effects_enabled():
        return "none"
    return requested


def apply_immersive_dark_mode(window: Any, enabled: bool) -> bool:
    """Match the DWM material tint to the app theme (best effort)."""
    try:
        hwnd = int(window.winId())
    except (AttributeError, TypeError, ValueError):
        return False
    value = 1 if enabled else 0
    for attribute in (
        _DWMWA_USE_IMMERSIVE_DARK_MODE,
        _DWMWA_USE_IMMERSIVE_DARK_MODE_BEFORE_20H1,
    ):
        if _dwm_set_int(hwnd, attribute, value):
            return True
    return False


def apply_redirection_bitmap_alpha(window: Any) -> bool:
    """Request alpha in the DWM redirection bitmap (optional, best effort)."""
    if windows_build() < _REDIRECTION_BITMAP_MIN_BUILD:
        return False
    try:
        hwnd = int(window.winId())
    except (AttributeError, TypeError, ValueError):
        return False
    return _dwm_set_int(hwnd, _DWMWA_REDIRECTIONBITMAP_ALPHA, 1)


def apply_system_backdrop(window: Any, kind: str = "mica") -> bool:
    """Apply a DWM-drawn backdrop behind ``window`` (a QQuickWindow).

    Returns True when the DWM call succeeded; False on unsupported OS, missing
    API, or any failure. Callers must treat False as "render normally".
    """
    backdrop_type = _BACKDROP_KINDS.get(kind)
    if backdrop_type is None or not supports_system_backdrop():
        return False
    try:
        hwnd = int(window.winId())
    except (AttributeError, TypeError, ValueError):
        return False
    return _dwm_set_backdrop(hwnd, backdrop_type)
