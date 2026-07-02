from PySide6.QtCore import Qt
from pytestqt.qtbot import QtBot

from ai_novel_studio.ui.demo_data import WorkspaceDemoData
from ai_novel_studio.ui.main_window import MainWindow
from ai_novel_studio.ui.pages.detached_chat_window import DetachedChatWindow
from ai_novel_studio.ui.panels.plot_chat_panel import PlotChatPanel


def test_plot_chat_renders_role_specific_left_and_right_bubbles(qtbot: QtBot) -> None:
    panel = PlotChatPanel(WorkspaceDemoData.sample().messages)
    qtbot.addWidget(panel)

    assert [bubble.property("chatRole") for bubble in panel.message_bubbles] == [
        "assistant",
        "user",
        "assistant",
    ]
    assert panel.bubble_rows[0].alignment() & Qt.AlignmentFlag.AlignLeft
    assert panel.bubble_rows[1].alignment() & Qt.AlignmentFlag.AlignRight


def test_send_appends_user_message_without_fabricating_assistant_reply(qtbot: QtBot) -> None:
    panel = PlotChatPanel(WorkspaceDemoData.sample().messages)
    qtbot.addWidget(panel)
    initial_count = len(panel.message_bubbles)

    panel.composer.setPlainText("让林默先检查信封的纸张来源。")
    panel.send_current_message()

    assert len(panel.message_bubbles) == initial_count + 1
    assert panel.message_bubbles[-1].property("chatRole") == "user"
    assert panel.message_bubbles[-1].text() == "让林默先检查信封的纸张来源。"
    assert panel.composer.toPlainText() == ""


def test_generate_brief_action_emits_explicit_signal(qtbot: QtBot) -> None:
    panel = PlotChatPanel(WorkspaceDemoData.sample().messages)
    qtbot.addWidget(panel)

    with qtbot.waitSignal(panel.brief_draft_requested, timeout=1000):
        panel.brief_button.click()


def test_detached_chat_copies_current_conversation(qtbot: QtBot) -> None:
    messages = WorkspaceDemoData.sample().messages
    window = DetachedChatWindow(messages)
    qtbot.addWidget(window)

    assert len(window.chat_panel.message_bubbles) == len(messages)
    assert window.chat_panel.detach_button.isHidden()


def test_main_window_opens_reusable_detached_chat(qtbot: QtBot) -> None:
    window = MainWindow()
    qtbot.addWidget(window)

    window.plot_chat_panel.detach_button.click()
    first = window.detached_chat_window
    assert first is not None
    assert first.isVisible()

    window.plot_chat_panel.detach_button.click()
    assert window.detached_chat_window is first
