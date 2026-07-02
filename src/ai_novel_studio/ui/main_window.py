from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QFrame,
    QLabel,
    QMainWindow,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from ai_novel_studio.ui.demo_data import WorkspaceDemoData
from ai_novel_studio.ui.panels.chapter_sidebar import ChapterSidebar
from ai_novel_studio.ui.panels.top_bar import TopBar
from ai_novel_studio.ui.theme import application_stylesheet


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("AI Novel Studio")
        self.setMinimumSize(960, 640)
        self.resize(1440, 900)
        self.setStyleSheet(application_stylesheet())

        self.data = WorkspaceDemoData.sample()
        surface = QWidget(self)
        surface.setObjectName("appSurface")
        layout = QVBoxLayout(surface)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(8)

        self.top_bar = TopBar(self.data, surface)
        layout.addWidget(self.top_bar)

        self.workspace_splitter = QSplitter(Qt.Orientation.Horizontal, surface)
        self.workspace_splitter.setObjectName("workspaceSplitter")
        self.workspace_splitter.setChildrenCollapsible(False)
        self.workspace_splitter.setHandleWidth(5)

        self.chapter_sidebar = ChapterSidebar(self.data, self.workspace_splitter)
        center = self._placeholder("manuscriptPlaceholder", "正文工作区", 430)
        right = self._placeholder("plotChatPlaceholder", "剧情商讨", 300)
        self.workspace_splitter.addWidget(self.chapter_sidebar)
        self.workspace_splitter.addWidget(center)
        self.workspace_splitter.addWidget(right)
        self.workspace_splitter.setStretchFactor(0, 0)
        self.workspace_splitter.setStretchFactor(1, 1)
        self.workspace_splitter.setStretchFactor(2, 0)
        self.workspace_splitter.setSizes([280, 760, 360])
        layout.addWidget(self.workspace_splitter, 1)
        self.setCentralWidget(surface)

    @staticmethod
    def _placeholder(object_name: str, title: str, minimum_width: int) -> QFrame:
        frame = QFrame()
        frame.setObjectName(object_name)
        frame.setProperty("class", "panelSurface")
        frame.setMinimumWidth(minimum_width)
        label = QLabel(title, frame)
        label.setObjectName("panelTitle")
        layout = QVBoxLayout(frame)
        layout.addWidget(label)
        layout.addStretch(1)
        return frame
