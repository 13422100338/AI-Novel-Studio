from collections.abc import Iterable

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
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
    brief_draft_requested = Signal()
    detach_requested = Signal()

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

        header = QHBoxLayout()
        title_stack = QVBoxLayout()
        title_stack.setSpacing(1)
        title_stack.addWidget(title)
        title_stack.addWidget(self.model_label)
        header.addLayout(title_stack)
        header.addStretch(1)
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

        self.brief_button = QPushButton("生成正式 Brief 草稿", self)
        self.brief_button.setAccessibleName("根据商讨内容生成正式章节 Brief 草稿")
        self.brief_button.clicked.connect(self.brief_draft_requested)

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
        composer_actions.addWidget(self.brief_button)
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

    def _append_bubble(self, role: str, text: str) -> None:
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

    def _scroll_to_bottom(self) -> None:
        scrollbar = self.scroll_area.verticalScrollBar()
        scrollbar.setValue(scrollbar.maximum())
