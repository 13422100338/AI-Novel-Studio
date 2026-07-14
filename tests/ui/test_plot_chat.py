from PySide6.QtCore import Qt
from pytestqt.qtbot import QtBot

from ai_novel_studio.ui.demo_data import WorkspaceDemoData
from ai_novel_studio.ui.main_window import MainWindow
from ai_novel_studio.ui.pages.detached_chat_window import DetachedChatWindow
from ai_novel_studio.ui.panels.plot_chat_panel import PlotChatPanel


class _Signal:
    def __init__(self) -> None:
        self.callbacks = []

    def connect(self, callback):  # type: ignore[no-untyped-def]
        self.callbacks.append(callback)

    def emit(self, *args):  # type: ignore[no-untyped-def]
        for callback in tuple(self.callbacks):
            callback(*args)


class _Coordinator:
    def __init__(self) -> None:
        self.chat_calls = []
        self.chat_chunk = _Signal()
        self.chat_finished = _Signal()
        self.requirement_ready = _Signal()
        self.brief_ready = _Signal()
        self.audit_ready = _Signal()
        self.task_failed = _Signal()
        self.usage_changed = _Signal()

    def start_chat(self, conversation, manuscript, limit):  # type: ignore[no-untyped-def]
        self.chat_calls.append((conversation, manuscript, limit))


class _Runtime:
    def __init__(self) -> None:
        self.coordinator = _Coordinator()
        self.settings_controller = None


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


def test_generate_requirement_action_emits_explicit_signal(qtbot: QtBot) -> None:
    panel = PlotChatPanel(WorkspaceDemoData.sample().messages)
    qtbot.addWidget(panel)

    assert panel.requirement_button.text() == "生成当前章要求"
    with qtbot.waitSignal(panel.chapter_requirement_requested, timeout=1000):
        panel.requirement_button.click()


def test_assistant_stream_chunks_are_batched_until_finish(qtbot: QtBot) -> None:
    panel = PlotChatPanel(())
    qtbot.addWidget(panel)
    panel.begin_assistant_response()

    panel.append_assistant_chunk("第一段")
    panel.append_assistant_chunk("第二段")

    assert panel.message_bubbles[-1].text() == ""
    assert panel._assistant_flush_timer.isActive()
    panel.finish_assistant_response()
    assert panel.message_bubbles[-1].text() == "第一段第二段"


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


def test_detached_chat_and_embedded_chat_share_one_conversation(qtbot: QtBot) -> None:
    runtime = _Runtime()
    window = MainWindow(model_runtime=runtime)
    qtbot.addWidget(window)
    window.open_detached_chat()
    assert window.detached_chat_window is not None
    detached_panel = window.detached_chat_window.chat_panel

    detached_panel.composer.setPlainText("从独立窗口发言")
    detached_panel.send_button.click()
    runtime.coordinator.chat_chunk.emit("同步回复")
    runtime.coordinator.chat_finished.emit()

    assert runtime.coordinator.chat_calls
    assert window.plot_chat_panel.message_bubbles[-2].text() == "从独立窗口发言"
    assert detached_panel.message_bubbles[-2].text() == "从独立窗口发言"
    assert window.plot_chat_panel.message_bubbles[-1].text() == "同步回复"
    assert detached_panel.message_bubbles[-1].text() == "同步回复"


def test_embedded_chat_updates_open_detached_chat(qtbot: QtBot) -> None:
    runtime = _Runtime()
    window = MainWindow(model_runtime=runtime)
    qtbot.addWidget(window)
    window.open_detached_chat()
    assert window.detached_chat_window is not None
    detached_panel = window.detached_chat_window.chat_panel

    window.plot_chat_panel.composer.setPlainText("从内嵌窗口发言")
    window.plot_chat_panel.send_button.click()
    runtime.coordinator.chat_chunk.emit("内嵌回复")
    runtime.coordinator.chat_finished.emit()

    assert runtime.coordinator.chat_calls
    assert window.plot_chat_panel.message_bubbles[-2].text() == "从内嵌窗口发言"
    assert detached_panel.message_bubbles[-2].text() == "从内嵌窗口发言"
    assert window.plot_chat_panel.message_bubbles[-1].text() == "内嵌回复"
    assert detached_panel.message_bubbles[-1].text() == "内嵌回复"
