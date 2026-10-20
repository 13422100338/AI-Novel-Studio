"""Application bootstrap for the QML shell (Frontend Wave F1)."""

from __future__ import annotations

import os
import sys
from collections.abc import Sequence
from pathlib import Path

from PySide6.QtCore import Property, QObject, QUrl, Signal, Slot
from PySide6.QtGui import QGuiApplication
from PySide6.QtQml import QQmlApplicationEngine

from ai_novel_studio.application.model_configuration_service import (
    ModelConfigurationService,
)
from ai_novel_studio.infrastructure.llm import (
    ModelConfigRepository,
    OpenAICompatibleAdapter,
    WindowsCredentialStore,
)
from ai_novel_studio.ui_qml.bridge.chat_markdown import ChatMarkdown
from ai_novel_studio.ui_qml.bridge.codex_controls_bridge import CodexControlsBridge
from ai_novel_studio.ui_qml.bridge.codex_session_bridge import CodexSessionController
from ai_novel_studio.ui_qml.bridge.harness_agent_bridge import (
    HarnessAgentCoordinator,
    HarnessAgentPort,
)
from ai_novel_studio.ui_qml.bridge.mock_novel_studio_facade import MockNovelStudioFacade
from ai_novel_studio.ui_qml.bridge.model_settings_bridge import ModelSettingsBridge
from ai_novel_studio.ui_qml.bridge.theme_provider import ThemeProvider
from ai_novel_studio.ui_qml.bridge.windows_backdrop import (
    apply_immersive_dark_mode,
    apply_redirection_bitmap_alpha,
    apply_system_backdrop,
    effective_backdrop_kind,
    supports_system_backdrop,
    transparency_effects_enabled,
    why_not_available,
    windows_build,
)
from ai_novel_studio.ui_qml.editor_runtime import ensure_editor_dist, ensure_qwebchannel_js

_FRONTEND_STATE: dict[int, tuple[MockNovelStudioFacade, ThemeProvider]] = {}
_CODEX_CONTROLS: dict[int, CodexControlsBridge] = {}


class EditorAssets(QObject):
    """Exposes the local editor page URL to QML (WebEngine mode)."""

    def __init__(self, index_url: str, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._index_url = index_url

    @Property(str, constant=True)
    def indexUrl(self) -> str:
        return self._index_url


class BackdropBridge(QObject):
    """Optional Windows 11 system-backdrop control for the Visual V0 lab.

    The glass course-correction demotes Mica / Desktop Acrylic to an optional,
    default-off experiment. QML calls ``apply(kind)`` from the experiment
    control panel; the bridge returns whether the DWM call succeeded so the
    page can show a live status. The production shell never uses this.
    """

    def __init__(self, window: QObject | None = None, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._window = window

    @Slot(str, result=bool)
    def apply(self, kind: str) -> bool:
        if self._window is None:
            return False
        from ai_novel_studio.ui_qml.bridge.windows_backdrop import (
            apply_system_backdrop,
        )

        return apply_system_backdrop(self._window, kind=kind)


class NativeGlassBridge(QObject):
    """System-backdrop capability/control bridge for the Native Glass Lab.

    Consumed only by the ``--native-glass-lab`` experiment page. It keeps the
    DWM knowledge in Python (platform, Windows build, "Transparency effects"
    setting, dark-mode tint, redirection-bitmap alpha) so QML only decides
    presentation. Every failure path keeps ``activeKind == "none"`` so the
    lab degrades to the app-internal glass route instead of pretending the
    wallpaper is visible.
    """

    capabilitiesChanged = Signal()

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._window: QObject | None = None
        self._requested_kind = "none"
        self._active_kind = "none"
        self._dark_mode = False

    def setWindow(self, window: QObject | None) -> None:
        self._window = window
        self.capabilitiesChanged.emit()

    @Property(str, constant=True)
    def platformName(self) -> str:
        if sys.platform.startswith("win"):
            return "win32"
        if sys.platform == "darwin":
            return "darwin"
        return sys.platform

    @Property(str, constant=True)
    def buildText(self) -> str:
        if os.name != "nt":
            return "-"
        return str(windows_build())

    @Property(bool, constant=True)
    def nativeSupported(self) -> bool:
        return supports_system_backdrop()

    @Property(bool, constant=True)
    def transparencyEffects(self) -> bool:
        return transparency_effects_enabled()

    @Property(str, constant=True)
    def unsupportedReason(self) -> str:
        if supports_system_backdrop() and transparency_effects_enabled():
            return ""
        return why_not_available()

    @Property(str, notify=capabilitiesChanged)
    def activeKind(self) -> str:
        return self._active_kind

    @Property(bool, notify=capabilitiesChanged)
    def nativeActive(self) -> bool:
        return self._active_kind != "none"

    @Slot(bool, result=bool)
    def setDarkMode(self, enabled: bool) -> bool:
        self._dark_mode = bool(enabled)
        if self._window is None:
            return False
        return apply_immersive_dark_mode(self._window, self._dark_mode)

    @Slot(result=bool)
    def refresh(self) -> bool:
        """Re-apply the active DWM attributes (after show / handle rebuild)."""
        if self._window is None or self._requested_kind == "none":
            return False
        return self.apply(self._requested_kind)

    @Slot(str, result=bool)
    def apply(self, kind: str) -> bool:
        if self._window is None:
            self._requested_kind = "none"
            self._active_kind = "none"
            self.capabilitiesChanged.emit()
            return False
        if kind == "none":
            # Truly clear the DWM backdrop (DWMSBT_NONE): switching back to
            # internal/solid must not leave the old material attached to the
            # window (review S2). Best effort; unsupported platforms no-op.
            if self._requested_kind != "none":
                apply_system_backdrop(self._window, kind="none")
            self._requested_kind = "none"
            self._active_kind = "none"
            self.capabilitiesChanged.emit()
            return False
        effective = effective_backdrop_kind(kind)
        if effective == "none":
            self._requested_kind = "none"
            self._active_kind = "none"
            self.capabilitiesChanged.emit()
            return False
        self._requested_kind = effective
        ok = apply_system_backdrop(self._window, kind=effective)
        if ok:
            # Best-effort extras: alpha in the DWM redirection bitmap
            # (24H2+ QML transparent windows) and the immersive dark tint.
            apply_redirection_bitmap_alpha(self._window)
            apply_immersive_dark_mode(self._window, self._dark_mode)
        self._active_kind = effective if ok else "none"
        self.capabilitiesChanged.emit()
        return ok


def _build_model_settings_bridge() -> ModelSettingsBridge | None:
    """Real model-settings wiring; returns None when unavailable.

    The config file lives under ``%APPDATA%\\AI Novel Studio``; keys go to the
    Windows credential store. Any construction failure keeps the settings page
    on its honest placeholder instead of crashing the shell.
    """
    try:
        appdata = os.environ.get("APPDATA")
        base = Path(appdata) if appdata else Path.home() / "AppData" / "Roaming"
        credentials = WindowsCredentialStore()
        repository = ModelConfigRepository(
            base / "AI Novel Studio" / "model-config.json",
            credentials,
        )
        service = ModelConfigurationService(
            repository=repository,
            credentials=credentials,
            adapters={"openai_compatible": OpenAICompatibleAdapter()},
        )
        return ModelSettingsBridge(service)
    except Exception:  # noqa: BLE001 - degrade to the honest placeholder page
        return None


def register_frontend_types(
    engine: QQmlApplicationEngine,
    facade: MockNovelStudioFacade | None = None,
    theme: ThemeProvider | None = None,
    *,
    demo_mode: bool = False,
    model_settings: ModelSettingsBridge | None = None,
) -> tuple[MockNovelStudioFacade, ThemeProvider]:
    """Expose the two F1 singletons to QML.

    Context properties are used deliberately instead of ``qmlRegisterSingletonType``:
    QML type registration is process-global, while tests need a fresh facade per
    engine. Only two well-named singletons exist, so this stays far from the
    "many implicit globals" the architecture plan warns about. The packaging ticket
    (F6) will move to a qmldir-backed typed registration for the single-process app.
    """
    if facade is None:
        agent_coordinator = (
            HarnessAgentCoordinator(HarnessAgentPort(), engine) if demo_mode else None
        )
        codex_controller = None if demo_mode else CodexSessionController(engine)
        facade = MockNovelStudioFacade(
            agent_coordinator=agent_coordinator,
            codex_controller=codex_controller,
            demo_mode=demo_mode,
        )
        application = QGuiApplication.instance()
        if codex_controller is not None and application is not None:
            application.aboutToQuit.connect(codex_controller.close)
    theme = theme if theme is not None else ThemeProvider()
    engine.rootContext().setContextProperty("Facade", facade)
    engine.rootContext().setContextProperty("Theme", theme)
    engine.rootContext().setContextProperty("ChatMarkup", ChatMarkdown(engine))
    codex_controls = CodexControlsBridge(engine)
    _CODEX_CONTROLS[id(engine)] = codex_controls
    engine.rootContext().setContextProperty("CodexSettings", codex_controls)
    if model_settings is not None:
        engine.rootContext().setContextProperty("ModelSettings", model_settings)
        engine.rootContext().setContextProperty("ModelSettingsReady", True)
    else:
        engine.rootContext().setContextProperty("ModelSettingsReady", False)
    engine.rootContext().setContextProperty("WritingPageUseWebEngine", False)
    # Visual V0 lab only: the active Qt Quick rendering backend (displayed in
    # the experiment control strip). Harmless placeholder for non-lab shells.
    engine.rootContext().setContextProperty("RenderBackendInfo", "unknown")
    return facade, theme


def app_qml_path() -> Path:
    return Path(__file__).resolve().parent / "qml" / "App.qml"


def visual_lab_qml_path() -> Path:
    """Standalone Visual V0 sample page (ideal-UI spec 15, stage V0)."""
    return Path(__file__).resolve().parent / "qml" / "VisualLab.qml"


def native_glass_lab_qml_path() -> Path:
    """Standalone Native Glass Lab page (isolation ticket: 原生毛玻璃测试界面)."""
    return Path(__file__).resolve().parent / "qml" / "NativeGlassLab.qml"


def create_engine(*, demo_mode: bool = False) -> QQmlApplicationEngine:
    """Build the TextArea-mode shell (tests and screenshot baseline)."""
    engine = QQmlApplicationEngine()
    engine.addImportPath(str(Path(__file__).resolve().parent / "qml"))
    facade, theme = register_frontend_types(engine, demo_mode=demo_mode)
    # Keep Python-side references alive for the engine's lifetime; otherwise the
    # QObject wrappers can be garbage collected and QML sees null singletons.
    _FRONTEND_STATE[id(engine)] = (facade, theme)
    engine.load(QUrl.fromLocalFile(str(app_qml_path())))
    return engine


def _use_webengine_from_args(args: Sequence[str]) -> bool:
    """Use the WebEngine editor unless the safe fallback is requested.

    The product editor is the WebEngine/ProseMirror surface: it owns the
    selection protocol, themed scrollbars and Markdown-preserving editing
    behavior. ``--textarea`` remains an explicit recovery switch for machines
    whose graphics stack cannot create the WebEngine shared context.
    """
    return "--textarea" not in args


def main(argv: Sequence[str] | None = None) -> int:
    args = list(argv) if argv is not None else sys.argv
    use_webengine = _use_webengine_from_args(args)
    args = [arg for arg in args if arg not in ("--textarea", "--webengine")]
    visual_lab = "--visual-lab" in args
    args = [arg for arg in args if arg != "--visual-lab"]
    native_glass_lab = "--native-glass-lab" in args
    args = [arg for arg in args if arg != "--native-glass-lab"]
    # Native glass (frameless DWM Desktop Acrylic shell) is an opt-in
    # experiment: the default shell is the flat opaque design. --glass
    # enables the experiment; --no-glass stays accepted as a no-op so
    # existing scripts and docs keep working.
    use_native_glass = "--glass" in args
    args = [arg for arg in args if arg not in ("--glass", "--no-glass")]
    # Demo data is an explicit development aid only: the production entry
    # always starts at the real empty state unless --demo is passed.
    demo_mode = "--demo" in args
    args = [arg for arg in args if arg != "--demo"]
    if use_webengine and not visual_lab and not native_glass_lab:
        # Ticket A: GPU rendering is the default. --software-gl is an explicit
        # diagnostic escape hatch, never the silent default. If black-strip
        # artifacts reappear on specific hardware, fix layout/repaint rather
        # than globally disabling GPU.
        if "--software-gl" in args:
            os.environ.setdefault("QTWEBENGINE_CHROMIUM_FLAGS", "--disable-gpu")
            args = [arg for arg in args if arg != "--software-gl"]
        from PySide6.QtWebEngineQuick import QtWebEngineQuick

        ensure_editor_dist()
        ensure_qwebchannel_js()
        QtWebEngineQuick.initialize()

    app = QGuiApplication(args)
    app.setApplicationName("AI Novel Studio (QML F1)")
    app.setOrganizationName("AI Novel Studio")
    engine = QQmlApplicationEngine()
    engine.addImportPath(str(Path(__file__).resolve().parent / "qml"))
    facade, theme = register_frontend_types(engine, demo_mode=demo_mode)
    if native_glass_lab:
        os.environ.setdefault("QT_QUICK_CONTROLS_STYLE", "Basic")
        # Frameless transparent windows need an alpha channel in the Qt Quick
        # swapchain; this must be requested before the first QQuickWindow is
        # created (Qt doc: QQuickWindow::setDefaultAlphaBuffer).
        from PySide6.QtQuick import QQuickWindow as _QQuickWindow

        _QQuickWindow.setDefaultAlphaBuffer(True)
        native_bridge = NativeGlassBridge(engine)
        engine.rootContext().setContextProperty("NativeGlassBridge", native_bridge)
        _FRONTEND_STATE[id(engine)] = (facade, theme)
        engine.load(QUrl.fromLocalFile(str(native_glass_lab_qml_path())))
        if not engine.rootObjects():
            return 1
        native_bridge.setWindow(engine.rootObjects()[0])
        # Default lab state: Desktop Acrylic when the machine supports it.
        # QML binds its nativeActive/activeKind to the bridge, so this also
        # drives the window transparency without a button click.
        theme.setTheme("dark")
        native_bridge.setDarkMode(True)
        native_bridge.apply("acrylic")
        engine.rootContext().setContextProperty(
            "RenderBackendInfo", _QQuickWindow.sceneGraphBackend() or "unknown"
        )
        return app.exec()
    if visual_lab:
        # Basic style so custom `background` items on TextField (VisualLab and
        # FormCard) actually apply instead of being ignored by the native style.
        os.environ.setdefault("QT_QUICK_CONTROLS_STYLE", "Basic")
        # Visual V0 sample page: no WebEngine, no editor bridge. It is a
        # standalone experiment surface, not the production shell.
        _FRONTEND_STATE[id(engine)] = (facade, theme)
        engine.load(QUrl.fromLocalFile(str(visual_lab_qml_path())))
        if not engine.rootObjects():
            return 1
        # System Mica / Desktop Acrylic is an optional, default-off experiment
        # (course correction): the lab window stays opaque and app-controlled.
        # The experiment panel can enable it on demand through BackdropBridge.
        lab_window = engine.rootObjects()[0]
        engine.rootContext().setContextProperty(
            "BackdropBridge", BackdropBridge(lab_window, engine)
        )
        from PySide6.QtQuick import QQuickWindow as _QQuickWindow

        engine.rootContext().setContextProperty(
            "RenderBackendInfo", _QQuickWindow.sceneGraphBackend() or "unknown"
        )
        return app.exec()
    engine.rootContext().setContextProperty("WritingPageUseWebEngine", use_webengine)
    # Production-shell system backdrop is opt-in (--glass, Windows 11 22621+
    # with "Transparency effects" enabled). The default shell is the flat
    # opaque design; with --glass the window gets a DWM Desktop Acrylic
    # material and QML keeps an opaque fallback whenever the bridge reports
    # nativeActive == false.
    glass_available = False
    if use_native_glass:
        from ai_novel_studio.ui_qml.bridge.windows_backdrop import (
            effective_backdrop_kind,
        )

        glass_available = effective_backdrop_kind("acrylic") != "none"
    if glass_available:
        # Alpha swapchain must be requested before the first QQuickWindow is
        # created (Qt doc: QQuickWindow::setDefaultAlphaBuffer).
        from PySide6.QtQuick import QQuickWindow as _QQuickWindow

        _QQuickWindow.setDefaultAlphaBuffer(True)
        native_bridge = NativeGlassBridge(engine)
        engine.rootContext().setContextProperty("NativeGlassBridge", native_bridge)
    engine.rootContext().setContextProperty("UseNativeGlass", glass_available)
    if use_webengine:
        from ai_novel_studio.ui_qml.bridge.editor_bridge import (
            EditorBridge,
            WebEditorDocumentSync,
        )

        editor_bridge = EditorBridge(engine)
        editor_sync = WebEditorDocumentSync(engine, facade, engine)
        editor_bridge.documentReady.connect(editor_sync.sync_force)
        facade.chapter_changed.connect(editor_sync.sync_if_chapter_changed)
        editor_bridge.save_requested.connect(
            lambda chapter_id, revision, markdown, content_hash: facade.saveFromEditor(
                chapter_id, revision, markdown
            )
        )
        editor_bridge.error.connect(facade.setSaveStatusText)
        editor_bridge.word_count_changed.connect(facade.setWebEngineWordCount)
        editor_bridge.selection_reference_changed.connect(facade.setSelectionReferenceJson)
        editor_bridge.chat_selection_changed.connect(facade.setChatSelectionJson)
        engine.rootContext().setContextProperty("pythonBridge", editor_bridge)
        dist = ensure_editor_dist()
        engine.rootContext().setContextProperty(
            "EditorAssets",
            EditorAssets((dist / "index.html").as_uri(), engine),
        )
    _FRONTEND_STATE[id(engine)] = (facade, theme)
    model_settings = _build_model_settings_bridge()
    if model_settings is not None:
        # Register both properties BEFORE loading QML so the page binds the
        # reactive bridge from the start (RC-2: ready-flag consistency).
        engine.rootContext().setContextProperty("ModelSettings", model_settings)
        engine.rootContext().setContextProperty("ModelSettingsReady", True)
    else:
        engine.rootContext().setContextProperty("ModelSettingsReady", False)
    engine.load(QUrl.fromLocalFile(str(app_qml_path())))
    if not engine.rootObjects():
        return 1
    if glass_available:
        # Attach the DWM material after the window exists; the QML retry
        # timer re-applies after the first show when DWM rejects the early
        # call (first-show race, same as the Native Glass Lab).
        native_bridge.setWindow(engine.rootObjects()[0])
        native_bridge.setDarkMode(theme.property("themeName") == "dark")
        native_bridge.apply("acrylic")
    return app.exec()
