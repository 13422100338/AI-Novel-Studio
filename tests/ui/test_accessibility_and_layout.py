from PySide6.QtCore import QPoint
from PySide6.QtWidgets import QPushButton
from pytestqt.qtbot import QtBot

from ai_novel_studio.ui.main_window import MainWindow


def test_primary_workspace_controls_have_accessible_names(qtbot: QtBot) -> None:
    window = MainWindow()
    qtbot.addWidget(window)

    unnamed = [
        button.text() for button in window.findChildren(QPushButton) if not button.accessibleName()
    ]
    assert unnamed == []


def test_workspace_minimum_widths_prevent_collapsed_panels(qtbot: QtBot) -> None:
    window = MainWindow()
    qtbot.addWidget(window)
    window.resize(1366, 768)
    window.show()
    qtbot.waitExposed(window)

    assert window.chapter_sidebar.minimumWidth() >= 250
    assert window.manuscript_panel.minimumWidth() >= 430
    assert window.plot_chat_panel.minimumWidth() >= 300
    sizes = window.workspace_splitter.sizes()
    assert all(size > 0 for size in sizes)
    assert sizes[1] > sizes[0]


def test_scroll_areas_resize_and_model_actions_are_explicitly_deferred(qtbot: QtBot) -> None:
    window = MainWindow()
    qtbot.addWidget(window)

    assert window.chapter_sidebar.scroll_area.widgetResizable()
    assert window.plot_chat_panel.scroll_area.widgetResizable()
    assert window.manuscript_panel.generate_button.isEnabled() is False
    assert "阶段 5" in window.manuscript_panel.generate_button.toolTip()


def test_settings_button_opens_reusable_phase_aware_dialog(qtbot: QtBot) -> None:
    window = MainWindow()
    qtbot.addWidget(window)

    window.top_bar.settings_button.click()
    first = window.settings_dialog
    assert first is not None
    assert first.isVisible()
    assert [first.tabs.tabText(index) for index in range(first.tabs.count())] == [
        "模型连接",
        "外观",
        "创作默认值",
    ]

    window.top_bar.settings_button.click()
    assert window.settings_dialog is first


def test_settings_actions_remain_visible_in_compact_window(qtbot: QtBot) -> None:
    window = MainWindow()
    qtbot.addWidget(window)
    window.top_bar.settings_button.click()
    dialog = window.settings_dialog
    assert dialog is not None

    dialog.resize(640, 480)
    dialog.show()
    qtbot.waitExposed(dialog)

    save_bottom = dialog.save_button.mapTo(
        dialog,
        QPoint(0, dialog.save_button.height()),
    ).y()
    assert dialog.content_scroll.widget() is dialog.tabs
    assert save_bottom <= dialog.contentsRect().bottom()
    assert dialog.save_button.isVisible()
