"""Unit tests for NativeGlassBridge (Native Glass Lab DWM bridge).

Pure-Python tests: every platform-dependent function is monkeypatched, so no
QML window, QGuiApplication, or real DWM call is involved.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from ai_novel_studio.ui_qml import bootstrap


class FakeWindow:
    """Minimal stand-in for a QML window: the bridge only needs winId()."""

    def __init__(self, win_id: int = 42) -> None:
        self._win_id = win_id

    def winId(self) -> int:
        return self._win_id


def _install_fakes(monkeypatch: pytest.MonkeyPatch) -> SimpleNamespace:
    fake = SimpleNamespace()
    fake.apply_result = True
    fake.effective_kind = lambda requested: requested
    fake.apply_system_backdrop_calls = []
    fake.redirection_calls = []
    fake.dark_mode_calls = []
    fake.supports = True
    fake.transparency = True
    fake.build = 26100
    fake.why_not = "DWM 调用失败"

    def apply_system_backdrop(window, kind="mica"):
        fake.apply_system_backdrop_calls.append((window, kind))
        return fake.apply_result

    def effective_backdrop_kind(requested):
        return fake.effective_kind(requested)

    def redirection_bitmap_alpha(window):
        fake.redirection_calls.append(window)
        return True

    def immersive_dark_mode(window, enabled):
        fake.dark_mode_calls.append((window, enabled))
        return True

    monkeypatch.setattr(bootstrap, "apply_system_backdrop", apply_system_backdrop)
    monkeypatch.setattr(bootstrap, "effective_backdrop_kind", effective_backdrop_kind)
    monkeypatch.setattr(bootstrap, "apply_redirection_bitmap_alpha", redirection_bitmap_alpha)
    monkeypatch.setattr(bootstrap, "apply_immersive_dark_mode", immersive_dark_mode)
    monkeypatch.setattr(bootstrap, "supports_system_backdrop", lambda: fake.supports)
    monkeypatch.setattr(bootstrap, "transparency_effects_enabled", lambda: fake.transparency)
    monkeypatch.setattr(bootstrap, "windows_build", lambda: fake.build)
    monkeypatch.setattr(bootstrap, "why_not_available", lambda: fake.why_not)
    monkeypatch.setattr(bootstrap.os, "name", "nt")
    monkeypatch.setattr(bootstrap.sys, "platform", "win32")
    return fake


@pytest.fixture
def glass_env(monkeypatch: pytest.MonkeyPatch) -> SimpleNamespace:
    env = _install_fakes(monkeypatch)
    env.bridge = bootstrap.NativeGlassBridge()
    return env


def _signal_spy(signal) -> list[bool]:
    emitted: list[bool] = []
    signal.connect(lambda: emitted.append(True))
    return emitted


def test_apply_before_set_window_returns_false_and_stays_none(glass_env) -> None:
    bridge = glass_env.bridge

    assert bridge.apply("acrylic") is False

    assert bridge.activeKind == "none"
    assert bridge.nativeActive is False
    assert bridge._requested_kind == "none"
    assert glass_env.apply_system_backdrop_calls == []


def test_apply_acrylic_success_sets_state_and_applies_extras(glass_env) -> None:
    window = FakeWindow()
    bridge = glass_env.bridge
    bridge.setWindow(window)

    assert bridge.apply("acrylic") is True

    assert bridge.activeKind == "acrylic"
    assert bridge.nativeActive is True
    assert bridge._requested_kind == "acrylic"
    assert glass_env.apply_system_backdrop_calls == [(window, "acrylic")]
    assert glass_env.redirection_calls == [window]
    assert glass_env.dark_mode_calls == [(window, False)]


def test_apply_failure_resets_active_state_and_emits(glass_env) -> None:
    glass_env.apply_result = False
    window = FakeWindow()
    bridge = glass_env.bridge
    bridge.setWindow(window)
    emitted = _signal_spy(bridge.capabilitiesChanged)

    assert bridge.apply("acrylic") is False

    assert bridge.activeKind == "none"
    assert bridge.nativeActive is False
    assert glass_env.apply_system_backdrop_calls == [(window, "acrylic")]
    assert glass_env.redirection_calls == []
    assert glass_env.dark_mode_calls == []
    assert emitted == [True]


def test_apply_none_after_active_kind_clears_dwm(glass_env) -> None:
    window = FakeWindow()
    bridge = glass_env.bridge
    bridge.setWindow(window)
    assert bridge.apply("acrylic") is True

    glass_env.apply_system_backdrop_calls.clear()
    glass_env.redirection_calls.clear()
    glass_env.dark_mode_calls.clear()

    assert bridge.apply("none") is False

    assert glass_env.apply_system_backdrop_calls == [(window, "none")]
    assert glass_env.redirection_calls == []
    assert glass_env.dark_mode_calls == []
    assert bridge.activeKind == "none"
    assert bridge.nativeActive is False
    assert bridge._requested_kind == "none"


def test_apply_none_when_never_active_skips_dwm(glass_env) -> None:
    window = FakeWindow()
    bridge = glass_env.bridge
    bridge.setWindow(window)

    assert bridge.apply("none") is False

    assert glass_env.apply_system_backdrop_calls == []
    assert bridge.activeKind == "none"
    assert bridge._requested_kind == "none"


def test_refresh_without_requested_kind_returns_false_and_skips_dwm(glass_env) -> None:
    bridge = glass_env.bridge

    assert bridge.refresh() is False
    bridge.setWindow(FakeWindow())
    assert bridge.refresh() is False
    assert glass_env.apply_system_backdrop_calls == []


def test_refresh_replays_requested_acrylic(glass_env) -> None:
    window = FakeWindow()
    bridge = glass_env.bridge
    bridge.setWindow(window)
    assert bridge.apply("acrylic") is True

    glass_env.apply_system_backdrop_calls.clear()
    glass_env.redirection_calls.clear()
    glass_env.dark_mode_calls.clear()

    assert bridge.refresh() is True

    assert glass_env.apply_system_backdrop_calls == [(window, "acrylic")]
    assert glass_env.redirection_calls == [window]
    assert glass_env.dark_mode_calls == [(window, False)]
    assert bridge.activeKind == "acrylic"
    assert bridge.nativeActive is True


def test_effective_backdrop_gate_none_blocks_dwm(glass_env) -> None:
    glass_env.effective_kind = lambda requested: "none"
    window = FakeWindow()
    bridge = glass_env.bridge
    bridge.setWindow(window)
    emitted = _signal_spy(bridge.capabilitiesChanged)

    assert bridge.apply("acrylic") is False

    assert glass_env.apply_system_backdrop_calls == []
    assert glass_env.redirection_calls == []
    assert glass_env.dark_mode_calls == []
    assert bridge.activeKind == "none"
    assert bridge.nativeActive is False
    assert bridge._requested_kind == "none"
    assert emitted == [True]


def test_set_dark_mode_before_and_after_window(glass_env) -> None:
    window = FakeWindow()
    bridge = glass_env.bridge

    assert bridge.setDarkMode(True) is False
    assert bridge._dark_mode is True
    assert glass_env.dark_mode_calls == []

    bridge.setWindow(window)

    assert bridge.setDarkMode(False) is True
    assert bridge._dark_mode is False
    assert glass_env.dark_mode_calls == [(window, False)]


def test_dark_mode_requested_before_window_applies_later(glass_env) -> None:
    window = FakeWindow()
    bridge = glass_env.bridge
    assert bridge.setDarkMode(True) is False

    bridge.setWindow(window)
    assert bridge.apply("acrylic") is True

    assert glass_env.dark_mode_calls == [(window, True)]


def test_properties_map_platform_functions(glass_env) -> None:
    bridge = glass_env.bridge

    assert bridge.platformName == "win32"
    assert bridge.buildText == "26100"
    assert bridge.nativeSupported is True
    assert bridge.transparencyEffects is True
    assert bridge.unsupportedReason == ""

    glass_env.build = 22621
    assert bridge.buildText == "22621"

    glass_env.supports = False
    assert bridge.nativeSupported is False
    assert bridge.unsupportedReason == glass_env.why_not

    glass_env.supports = True
    glass_env.transparency = False
    assert bridge.nativeSupported is True
    assert bridge.transparencyEffects is False
    assert bridge.unsupportedReason == glass_env.why_not


def test_non_windows_platform_and_build_text(monkeypatch) -> None:
    monkeypatch.setattr(bootstrap.os, "name", "posix")
    monkeypatch.setattr(bootstrap.sys, "platform", "linux")
    monkeypatch.setattr(bootstrap, "windows_build", lambda: 0)
    monkeypatch.setattr(bootstrap, "supports_system_backdrop", lambda: False)
    monkeypatch.setattr(bootstrap, "transparency_effects_enabled", lambda: False)
    monkeypatch.setattr(bootstrap, "why_not_available", lambda: "非 Windows 平台")
    bridge = bootstrap.NativeGlassBridge()

    assert bridge.platformName == "linux"
    assert bridge.buildText == "-"
    assert bridge.unsupportedReason == "非 Windows 平台"

    monkeypatch.setattr(bootstrap.sys, "platform", "darwin")
    assert bridge.platformName == "darwin"
