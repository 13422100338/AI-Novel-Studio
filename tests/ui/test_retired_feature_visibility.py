from pytestqt.qtbot import QtBot

from ai_novel_studio.ui.demo_data import WorkspaceDemoData
from ai_novel_studio.ui.pages.settings_dialog import SettingsDialog
from ai_novel_studio.ui.pages.style_rules_window import StyleRulesWindow


def test_settings_hide_retired_agent_route_without_removing_its_control(
    qtbot: QtBot,
) -> None:
    dialog = SettingsDialog()
    qtbot.addWidget(dialog)

    assert dialog.agent_model_combo.isHidden()
    assert dialog.agent_model_combo.count() >= 1


def test_style_workspace_only_exposes_manual_samples(qtbot: QtBot) -> None:
    window = StyleRulesWindow(WorkspaceDemoData.sample())
    qtbot.addWidget(window)

    assert not window.tabs.isTabVisible(0)
    assert window.tabs.isTabVisible(1)
    assert not window.tabs.isTabVisible(2)
    assert window.tabs.currentIndex() == 1
