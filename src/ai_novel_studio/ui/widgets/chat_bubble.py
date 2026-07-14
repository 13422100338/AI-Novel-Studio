from PySide6.QtCore import Qt
from PySide6.QtWidgets import QFrame, QLabel, QVBoxLayout, QWidget


class ChatBubble(QFrame):
    def __init__(self, role: str, text: str, parent: QWidget | None = None) -> None:
        if role not in {"assistant", "user"}:
            raise ValueError("chat role must be assistant or user")
        super().__init__(parent)
        self.setProperty("chatRole", role)
        self.setObjectName("chatBubble")
        self.setMaximumWidth(440)
        self._text = text

        self._label = QLabel(self._text, self)
        self._label.setWordWrap(True)
        self._label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self._label.setAccessibleName("AI 消息" if role == "assistant" else "用户消息")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 9, 12, 9)
        layout.addWidget(self._label)

    def text(self) -> str:
        return self._text

    def set_text(self, text: str) -> None:
        self._text = text
        self._label.setText(self._text)

    def append_text(self, text: str) -> None:
        self._text += text
        self._label.setText(self._text)
