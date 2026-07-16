from pytestqt.qtbot import QtBot

from ai_novel_studio.ui.demo_data import WorkspaceDemoData
from ai_novel_studio.ui.pages.settings_dialog import SettingsDialog
from ai_novel_studio.ui.pages.style_rules_window import StyleRulesWindow


def test_settings_expose_restored_agent_route(
    qtbot: QtBot,
) -> None:
    dialog = SettingsDialog()
    qtbot.addWidget(dialog)

    assert not dialog.agent_model_combo.isHidden()
    assert dialog.agent_model_combo.count() >= 1


def test_style_workspace_only_exposes_manual_samples(qtbot: QtBot) -> None:
    window = StyleRulesWindow(WorkspaceDemoData.sample())
    qtbot.addWidget(window)

    assert not window.tabs.isTabVisible(0)
    assert window.tabs.isTabVisible(1)
    assert not window.tabs.isTabVisible(2)
    assert window.tabs.currentIndex() == 1
