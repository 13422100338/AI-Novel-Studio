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


def test_current_chapter_requirement_is_visible_and_directly_editable(qtbot: QtBot) -> None:
    panel = ManuscriptPanel(WorkspaceDemoData.sample())
    qtbot.addWidget(panel)

    assert "林默" in panel.chapter_requirement.toPlainText()
    assert panel.chapter_requirement.isReadOnly() is False
    panel.chapter_requirement.setPlainText("本章必须让林默主动前往旧港。")
    assert panel.chapter_requirement.toPlainText() == "本章必须让林默主动前往旧港。"


def test_locked_requirement_rejects_plot_chat_replacement(qtbot: QtBot) -> None:
    panel = ManuscriptPanel(WorkspaceDemoData.sample())
    qtbot.addWidget(panel)
    original = panel.chapter_requirement.toPlainText()

    panel.toggle_requirement_lock()

    assert panel.chapter_requirement.isReadOnly() is True
    assert panel.apply_requirement_draft("不应覆盖") is False
    assert panel.chapter_requirement.toPlainText() == original

    panel.toggle_requirement_lock()
    assert panel.apply_requirement_draft("新的正式要求") is True
    assert panel.chapter_requirement.toPlainText() == "新的正式要求"


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


def test_brief_sections_expose_hover_explanations(qtbot: QtBot) -> None:
    dialog = BriefDialog(WorkspaceDemoData.sample().brief)
    qtbot.addWidget(dialog)

    assert set(dialog.section_help_buttons) == {
        "戏剧功能",
        "必须事件",
        "知识边界",
        "叙事线索",
        "文风",
        "自由空间",
    }
    for title, button in dialog.section_help_buttons.items():
        assert button.text() == "!"
        assert button.toolTip()
        assert button.accessibleName() == f"{title}说明"
    assert "为什么需要这一章" in dialog.section_help_buttons["戏剧功能"].toolTip()
    assert "不得省略" in dialog.section_help_buttons["必须事件"].toolTip()


def test_main_window_opens_reusable_brief_dialog(qtbot: QtBot) -> None:
    window = MainWindow()
    qtbot.addWidget(window)

    window.manuscript_panel.brief_button.click()
    first = window.brief_dialog
    assert first is not None
    assert first.isVisible()

    window.manuscript_panel.brief_button.click()
    assert window.brief_dialog is first


def test_plot_chat_action_never_uses_old_demo_draft_when_requirement_is_locked(
    qtbot: QtBot,
) -> None:
    window = MainWindow()
    qtbot.addWidget(window)
    window.manuscript_panel.chapter_requirement.clear()
    window.manuscript_panel.toggle_requirement_lock()

    window.plot_chat_panel.requirement_button.click()

    assert "未请求" in window.manuscript_panel.requirement_status.text()
    assert window.manuscript_panel.chapter_requirement.toPlainText() == ""
