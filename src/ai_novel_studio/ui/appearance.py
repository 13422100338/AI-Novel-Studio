from __future__ import annotations

from enum import StrEnum

from PySide6.QtCore import QObject, QSettings, Qt, Signal
from PySide6.QtWidgets import QApplication

from ai_novel_studio.ui.theme import application_stylesheet


class ThemePreference(StrEnum):
    LIGHT = "light"
    SYSTEM = "system"


class InformationDensity(StrEnum):
    NORMAL = "normal"
    COMPACT = "compact"
    COMFORTABLE = "comfortable"


def _settings() -> QSettings:
    return QSettings(
        QSettings.Format.IniFormat,
        QSettings.Scope.UserScope,
        "AI Novel Studio",
        "AI Novel Studio",
    )


class AppearanceManager(QObject):
    appearance_changed = Signal(str, str)

    def __init__(self) -> None:
        super().__init__()
        settings = _settings()
        self._theme = self._safe_theme(settings.value("appearance/theme", "light"))
        self._density = self._safe_density(settings.value("appearance/density", "normal"))
        self._application: QApplication | None = None

    @property
    def theme(self) -> ThemePreference:
        return self._theme

    @property
    def density(self) -> InformationDensity:
        return self._density

    def install(self, application: QApplication) -> None:
        self._application = application
        style_hints = application.styleHints()
        color_scheme_changed = getattr(style_hints, "colorSchemeChanged", None)
        if color_scheme_changed is not None:
            color_scheme_changed.connect(self._system_color_scheme_changed)
        self.apply()

    def set_preferences(
        self,
        theme: str | ThemePreference,
        density: str | InformationDensity,
    ) -> None:
        selected_theme = self._safe_theme(theme)
        selected_density = self._safe_density(density)
        settings = _settings()
        settings.setValue("appearance/theme", selected_theme.value)
        settings.setValue("appearance/density", selected_density.value)
        settings.sync()
        self._theme = selected_theme
        self._density = selected_density
        self.apply()
        self.appearance_changed.emit(selected_theme.value, selected_density.value)

    def stylesheet(self) -> str:
        return application_stylesheet(
            theme=self._resolved_theme(),
            density=self._density.value,
        )

    def apply(self) -> None:
        if self._application is not None:
            self._application.setStyleSheet(self.stylesheet())

    def _resolved_theme(self) -> str:
        if self._theme == ThemePreference.LIGHT or self._application is None:
            return "light"
        color_scheme = self._application.styleHints().colorScheme()
        return "dark" if color_scheme == Qt.ColorScheme.Dark else "light"

    def _system_color_scheme_changed(self, _scheme: Qt.ColorScheme) -> None:
        if self._theme == ThemePreference.SYSTEM:
            self.apply()
            self.appearance_changed.emit(self._theme.value, self._density.value)

    @staticmethod
    def _safe_theme(value: object) -> ThemePreference:
        try:
            return ThemePreference(str(value))
        except ValueError:
            return ThemePreference.LIGHT

    @staticmethod
    def _safe_density(value: object) -> InformationDensity:
        try:
            return InformationDensity(str(value))
        except ValueError:
            return InformationDensity.NORMAL


_manager: AppearanceManager | None = None


def appearance_manager() -> AppearanceManager:
    global _manager
    if _manager is None:
        _manager = AppearanceManager()
    return _manager
