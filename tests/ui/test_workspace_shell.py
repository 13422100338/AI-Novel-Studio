from PySide6.QtCore import Qt
from pytestqt.qtbot import QtBot

from ai_novel_studio.ui.demo_data import WorkspaceDemoData
from ai_novel_studio.ui.main_window import MainWindow
from ai_novel_studio.ui.panels.chapter_sidebar import ChapterSidebar
from ai_novel_studio.ui.panels.top_bar import TopBar


def test_main_window_composes_top_bar_and_three_resizable_panes(qtbot: QtBot) -> None:
    window = MainWindow()
    qtbot.addWidget(window)

    assert isinstance(window.top_bar, TopBar)
    assert window.workspace_splitter.count() == 3
    assert [window.workspace_splitter.widget(index).objectName() for index in range(3)] == [
        "chapterSidebar",
        "manuscriptPanel",
        "plotChatPanel",
    ]
    assert window.workspace_splitter.childrenCollapsible() is False
    assert window.workspace_splitter.handleWidth() >= 5


def test_top_bar_exposes_metrics_and_prominent_settings(qtbot: QtBot) -> None:
    top_bar = TopBar(WorkspaceDemoData.sample())
    qtbot.addWidget(top_bar)

    assert top_bar.project_label.text() == "雾港来信"
    assert top_bar.metrics["input"].value_text() == "约 18.6K"
    assert top_bar.metrics["output"].value_text() == "8K"
    assert top_bar.settings_button.text() == "设置"
    assert top_bar.settings_button.accessibleName()


def test_chapter_sidebar_is_scrollable_and_sections_collapse(qtbot: QtBot) -> None:
    sidebar = ChapterSidebar(WorkspaceDemoData.sample())
    qtbot.addWidget(sidebar)

    assert sidebar.scroll_area.widgetResizable() is True
    assert sidebar.scroll_area.verticalScrollBarPolicy() == Qt.ScrollBarPolicy.ScrollBarAsNeeded
    assert sidebar.chapter_tree.topLevelItemCount() == 1
    assert sidebar.chapter_tree.topLevelItem(0).isExpanded() is True
    assert sidebar.chapter_section.is_expanded() is True
    sidebar.chapter_section.set_expanded(False)
    assert sidebar.chapter_tree.isHidden() is True


def test_character_menu_selects_edits_and_deletes_local_mock(qtbot: QtBot) -> None:
    sidebar = ChapterSidebar(WorkspaceDemoData.sample())
    qtbot.addWidget(sidebar)

    assert sidebar.character_combo.count() == 2
    sidebar.character_combo.setCurrentIndex(1)
    assert "担心林默" in sidebar.psychology_edit.toPlainText()

    sidebar.psychology_edit.setPlainText("新的心理状态")
    sidebar.apply_character_edit()
    assert sidebar.character_status("character-su")["psychology"] == "新的心理状态"

    sidebar.delete_current_character()
    assert sidebar.character_combo.count() == 1


def test_chapter_selection_emits_stable_demo_id(qtbot: QtBot) -> None:
    sidebar = ChapterSidebar(WorkspaceDemoData.sample())
    qtbot.addWidget(sidebar)

    with qtbot.waitSignal(sidebar.chapter_selected, timeout=1000) as blocker:
        chapter_item = sidebar.chapter_tree.topLevelItem(0).child(1)
        sidebar.chapter_tree.setCurrentItem(chapter_item)

    assert blocker.args == ["chapter-2"]
