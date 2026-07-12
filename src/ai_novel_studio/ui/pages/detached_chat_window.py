from collections.abc import Iterable

from PySide6.QtWidgets import QMainWindow, QWidget

from ai_novel_studio.ui.demo_data import DemoMessage
from ai_novel_studio.ui.panels.plot_chat_panel import PlotChatPanel


class DetachedChatWindow(QMainWindow):
    def __init__(self, messages: Iterable[DemoMessage], parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("剧情商讨 · AI Novel Studio")
        self.setMinimumSize(620, 680)
        self.resize(760, 820)
        self.chat_panel = PlotChatPanel(messages, self, allow_detach=False)
        self.setCentralWidget(self.chat_panel)
