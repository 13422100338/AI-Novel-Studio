from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QSettings
from PySide6.QtWidgets import QApplication, QLabel, QPushButton, QTabWidget, QVBoxLayout, QWidget
from pytestqt.qtbot import QtBot

from ai_novel_studio.ui.i18n import Language, LocalizationManager


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


def test_language_switch_translates_open_widgets_and_restores_chinese(
    qtbot: QtBot, tmp_path: Path
) -> None:
    _isolated_settings(tmp_path)
    root = QWidget()
    qtbot.addWidget(root)
    layout = QVBoxLayout(root)
    label = QLabel("剧情商讨", root)
    button = QPushButton("生成正文", root)
    tabs = QTabWidget(root)
    tabs.addTab(QWidget(tabs), "记忆库")
    layout.addWidget(label)
    layout.addWidget(button)
    layout.addWidget(tabs)

    manager = LocalizationManager()
    manager.set_language(Language.ENGLISH)
    manager.apply(root)

    assert label.text() == "Plot discussion"
    assert button.text() == "Generate prose"
    assert tabs.tabText(0) == "Memory library"

    manager.set_language(Language.CHINESE)
    manager.apply(root)

    assert label.text() == "剧情商讨"
    assert button.text() == "生成正文"
    assert tabs.tabText(0) == "记忆库"


def test_language_choice_is_persisted(tmp_path: Path) -> None:
    _isolated_settings(tmp_path)
    manager = LocalizationManager()
    manager.set_language(Language.ENGLISH)

    restored = LocalizationManager()

    assert restored.language == Language.ENGLISH


def test_dynamic_status_text_is_translated_after_layout_update(
    qtbot: QtBot, tmp_path: Path, qapp: QApplication
) -> None:
    _isolated_settings(tmp_path)
    root = QWidget()
    qtbot.addWidget(root)
    layout = QVBoxLayout(root)
    label = QLabel("剧情模型 · 尚未连接", root)
    layout.addWidget(label)
    manager = LocalizationManager()
    manager.set_language(Language.ENGLISH)
    manager.install(qapp)
    root.show()

    label.setText("剧情模型 · 已连接")
    qtbot.waitUntil(lambda: label.text() == "Plot model · Connected")
