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
from ai_novel_studio.ui.pages.brief_dialog import BriefDialog
from ai_novel_studio.ui.panels.chapter_sidebar import ChapterSidebar
from ai_novel_studio.ui.panels.manuscript_panel import ManuscriptPanel
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
        self.brief_dialog: BriefDialog | None = None
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
        self.manuscript_panel = ManuscriptPanel(self.data, self.workspace_splitter)
        right = self._placeholder("plotChatPlaceholder", "剧情商讨", 300)
        self.workspace_splitter.addWidget(self.chapter_sidebar)
        self.workspace_splitter.addWidget(self.manuscript_panel)
        self.workspace_splitter.addWidget(right)
        self.workspace_splitter.setStretchFactor(0, 0)
        self.workspace_splitter.setStretchFactor(1, 1)
        self.workspace_splitter.setStretchFactor(2, 0)
        self.workspace_splitter.setSizes([280, 760, 360])
        layout.addWidget(self.workspace_splitter, 1)
        self.setCentralWidget(surface)
        self.manuscript_panel.brief_requested.connect(self.open_brief_dialog)

    def open_brief_dialog(self) -> None:
        if self.brief_dialog is None:
            self.brief_dialog = BriefDialog(self.data.brief, self)
        self.brief_dialog.show()
        self.brief_dialog.raise_()
        self.brief_dialog.activateWindow()

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
