from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QSettings
from PySide6.QtWidgets import QApplication

from ai_novel_studio.ui.appearance import (
    AppearanceManager,
    InformationDensity,
    ThemePreference,
)
from ai_novel_studio.ui.theme import application_stylesheet


def _isolated_settings(tmp_path: Path) -> None:
    QSettings.setPath(
        QSettings.Format.IniFormat,
        QSettings.Scope.UserScope,
        str(tmp_path),
    )
    settings = QSettings(
        QSettings.Format.IniFormat,
        QSettings.Scope.UserScope,
        "AI Novel Studio",
        "AI Novel Studio",
    )
    settings.clear()
    settings.sync()


def test_appearance_preferences_are_persisted(tmp_path: Path) -> None:
    _isolated_settings(tmp_path)
    manager = AppearanceManager()

    manager.set_preferences(ThemePreference.SYSTEM, InformationDensity.COMPACT)

    restored = AppearanceManager()
    assert restored.theme == ThemePreference.SYSTEM
    assert restored.density == InformationDensity.COMPACT


def test_density_options_produce_distinct_widget_spacing() -> None:
    normal = application_stylesheet(density="normal")
    compact = application_stylesheet(density="compact")
    comfortable = application_stylesheet(density="comfortable")

    assert "min-height: 30px" in normal
    assert "min-height: 24px" in compact
    assert "min-height: 36px" in comfortable


def test_installed_manager_applies_stylesheet(
    qapp: QApplication, tmp_path: Path
) -> None:
    _isolated_settings(tmp_path)
    manager = AppearanceManager()
    manager.install(qapp)

    manager.set_preferences(ThemePreference.LIGHT, InformationDensity.COMFORTABLE)

    assert "min-height: 36px" in qapp.styleSheet()
