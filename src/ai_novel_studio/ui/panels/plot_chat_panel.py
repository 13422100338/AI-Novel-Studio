from collections.abc import Iterable

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from ai_novel_studio.ui.demo_data import DemoMessage
from ai_novel_studio.ui.widgets.chat_bubble import ChatBubble


class PlotChatPanel(QFrame):
    message_sent = Signal(str)
    chapter_requirement_requested = Signal()
    detach_requested = Signal()
    agent_trace_requested = Signal()

    def __init__(
        self,
        messages: Iterable[DemoMessage],
        parent: QWidget | None = None,
        *,
        allow_detach: bool = True,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("plotChatPanel")
        self.setMinimumWidth(300)
        self._messages = list(messages)
        self._streaming_bubble: ChatBubble | None = None
        self.message_bubbles: list[ChatBubble] = []
        self.bubble_rows: list[QHBoxLayout] = []

        title = QLabel("剧情商讨", self)
        title.setObjectName("panelTitle")
        self.model_label = QLabel("剧情模型 · 尚未连接", self)
        self.model_label.setObjectName("mutedLabel")
        self.detach_button = QPushButton("独立窗口", self)
        self.detach_button.setAccessibleName("在独立窗口中打开剧情商讨")
        self.detach_button.setToolTip("独立显示当前对话")
        self.detach_button.setVisible(allow_detach)
        self.detach_button.clicked.connect(self.detach_requested)
        self.agent_mode_toggle = QCheckBox("Agent 模式", self)
        self.agent_mode_toggle.setObjectName("agentModeToggle")
        self.agent_mode_toggle.setToolTip("开启后，剧情商讨会使用只读工具检索记忆库与章节证据。")
        self.agent_trace_button = QPushButton("工具追踪", self)
        self.agent_trace_button.setObjectName("agentTraceButton")
        self.agent_trace_button.setAccessibleName("查看 Agent 工具追踪")
        self.agent_trace_button.setToolTip("查看最近一次 Agent 工具调用与证据来源")
        self.agent_trace_button.clicked.connect(self.agent_trace_requested)

        header = QHBoxLayout()
        title_stack = QVBoxLayout()
        title_stack.setSpacing(1)
        title_stack.addWidget(title)
        title_stack.addWidget(self.model_label)
        header.addLayout(title_stack)
        header.addStretch(1)
        header.addWidget(self.agent_mode_toggle)
        header.addWidget(self.agent_trace_button)
        header.addWidget(self.detach_button)

        self.scroll_area = QScrollArea(self)
        self.scroll_area.setObjectName("plotChatScroll")
        self.scroll_area.setWidgetResizable(True)
        self.scroll_area.setFrameShape(QFrame.Shape.NoFrame)
        self.conversation = QWidget(self.scroll_area)
        self.conversation.setObjectName("appSurface")
        self.conversation_layout = QVBoxLayout(self.conversation)
        self.conversation_layout.setContentsMargins(4, 8, 4, 8)
        self.conversation_layout.setSpacing(10)
        self.conversation_layout.addStretch(1)
        self.scroll_area.setWidget(self.conversation)
        for message in self._messages:
            self._append_bubble(message.role, message.text)

        self.requirement_button = QPushButton("生成当前章要求", self)
        self.requirement_button.setAccessibleName("把商讨内容整理成正式当前章要求")
        self.requirement_button.setToolTip("使用剧情商讨模型整理正式当前章要求")
        self.requirement_button.clicked.connect(self.chapter_requirement_requested)

        self.composer = QPlainTextEdit(self)
        self.composer.setObjectName("chatComposer")
        self.composer.setAccessibleName("剧情商讨消息输入框")
        self.composer.setPlaceholderText("和剧情模型讨论人物动机、转折、伏笔……")
        self.composer.setMaximumHeight(110)
        self.send_button = QPushButton("发送", self)
        self.send_button.setProperty("buttonRole", "primary")
        self.send_button.setAccessibleName("发送剧情商讨消息")
        self.send_button.clicked.connect(self.send_current_message)
        composer_actions = QHBoxLayout()
        composer_actions.addWidget(self.requirement_button)
        composer_actions.addStretch(1)
        composer_actions.addWidget(self.send_button)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 10)
        layout.setSpacing(8)
        layout.addLayout(header)
        layout.addWidget(self.scroll_area, 1)
        layout.addWidget(self.composer)
        layout.addLayout(composer_actions)

    def send_current_message(self) -> None:
        text = self.composer.toPlainText().strip()
        if not text:
            return
        self._messages.append(DemoMessage("user", text))
        self._append_bubble("user", text)
        self.composer.clear()
        self.message_sent.emit(text)
        self._scroll_to_bottom()

    def message_snapshot(self) -> tuple[DemoMessage, ...]:
        return tuple(self._messages)

    def agent_mode_enabled(self) -> bool:
        return self.agent_mode_toggle.isChecked()

    def begin_assistant_response(self) -> None:
        if self._streaming_bubble is not None:
            return
        self.send_button.setEnabled(False)
        self.model_label.setText("剧情模型 · 正在回复…")
        self._streaming_bubble = self._append_bubble("assistant", "")

    def append_assistant_chunk(self, text: str) -> None:
        if self._streaming_bubble is None:
            self.begin_assistant_response()
        if self._streaming_bubble is not None:
            self._streaming_bubble.append_text(text)
        self._scroll_to_bottom()

    def finish_assistant_response(self) -> None:
        if self._streaming_bubble is not None:
            text = self._streaming_bubble.text().strip()
            if text:
                self._messages.append(DemoMessage("assistant", text))
        self._streaming_bubble = None
        self.send_button.setEnabled(True)
        self.model_label.setText("剧情模型 · 已连接")
        self._scroll_to_bottom()

    def show_model_error(self, message: str) -> None:
        if self._streaming_bubble is not None and not self._streaming_bubble.text():
            self._streaming_bubble.set_text(f"未能获得回复：{message}")
        self._streaming_bubble = None
        self.send_button.setEnabled(True)
        self.requirement_button.setEnabled(True)
        self.model_label.setText("剧情模型 · 调用失败")

    def set_requirement_busy(self, busy: bool) -> None:
        self.requirement_button.setEnabled(not busy)
        self.requirement_button.setText("正在整理…" if busy else "生成当前章要求")

    def _append_bubble(self, role: str, text: str) -> ChatBubble:
        bubble = ChatBubble(role, text, self.conversation)
        row = QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        if role == "user":
            row.setAlignment(Qt.AlignmentFlag.AlignRight)
            row.addStretch(1)
            row.addWidget(bubble)
        else:
            row.setAlignment(Qt.AlignmentFlag.AlignLeft)
            row.addWidget(bubble)
            row.addStretch(1)
        self.conversation_layout.insertLayout(self.conversation_layout.count() - 1, row)
        self.message_bubbles.append(bubble)
        self.bubble_rows.append(row)
        return bubble

    def _scroll_to_bottom(self) -> None:
        scrollbar = self.scroll_area.verticalScrollBar()
        scrollbar.setValue(scrollbar.maximum())
