from pytestqt.qtbot import QtBot

from ai_novel_studio.ui.demo_data import WorkspaceDemoData
from ai_novel_studio.ui.main_window import MainWindow
from ai_novel_studio.ui.pages.brief_dialog import BriefDialog
from ai_novel_studio.ui.panels.manuscript_panel import ManuscriptPanel


def test_manuscript_panel_is_editable_and_keeps_custom_token_limit(qtbot: QtBot) -> None:
    panel = ManuscriptPanel(WorkspaceDemoData.sample())
    qtbot.addWidget(panel)

    assert panel.editor.isReadOnly() is False
    assert panel.editor.toPlainText()
    assert panel.output_token_limit.value() == 8000
    panel.output_token_limit.setValue(16000)
    assert panel.output_token_limit.value() == 16000


def test_font_size_updates_editor_without_changing_content(qtbot: QtBot) -> None:
    panel = ManuscriptPanel(WorkspaceDemoData.sample())
    qtbot.addWidget(panel)
    original = panel.editor.toPlainText()

    panel.font_size.setValue(22)

    assert round(panel.editor.font().pointSizeF()) == 22
    assert panel.editor.toPlainText() == original


def test_editor_updates_visible_character_count(qtbot: QtBot) -> None:
    panel = ManuscriptPanel(WorkspaceDemoData.sample())
    qtbot.addWidget(panel)

    panel.editor.setPlainText("你好 世界\n")

    assert panel.word_count_label.text() == "4 字"


def test_brief_dialog_freezes_and_clones_stale_revision(qtbot: QtBot) -> None:
    dialog = BriefDialog(WorkspaceDemoData.sample().brief)
    qtbot.addWidget(dialog)

    assert dialog.brief_status() == "草稿"
    assert dialog.section_editors
    assert dialog.source_badges
    dialog.freeze_brief()
    assert dialog.brief_status() == "已冻结"
    assert all(editor.isReadOnly() for editor in dialog.section_editors.values())

    dialog.mark_stale()
    assert dialog.brief_status() == "已过期"
    dialog.clone_as_draft()
    assert dialog.brief_status() == "草稿"
    assert all(not editor.isReadOnly() for editor in dialog.section_editors.values())


def test_main_window_opens_reusable_brief_dialog(qtbot: QtBot) -> None:
    window = MainWindow()
    qtbot.addWidget(window)

    window.manuscript_panel.brief_button.click()
    first = window.brief_dialog
    assert first is not None
    assert first.isVisible()

    window.manuscript_panel.brief_button.click()
    assert window.brief_dialog is first
