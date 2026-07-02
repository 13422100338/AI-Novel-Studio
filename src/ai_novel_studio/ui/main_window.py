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
from ai_novel_studio.ui.pages.audit_window import AuditWindow
from ai_novel_studio.ui.pages.brief_dialog import BriefDialog
from ai_novel_studio.ui.pages.detached_chat_window import DetachedChatWindow
from ai_novel_studio.ui.pages.memory_window import MemoryWindow
from ai_novel_studio.ui.pages.style_rules_window import StyleRulesWindow
from ai_novel_studio.ui.panels.chapter_sidebar import ChapterSidebar
from ai_novel_studio.ui.panels.manuscript_panel import ManuscriptPanel
from ai_novel_studio.ui.panels.plot_chat_panel import PlotChatPanel
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
        self.detached_chat_window: DetachedChatWindow | None = None
        self.memory_window: MemoryWindow | None = None
        self.style_rules_window: StyleRulesWindow | None = None
        self.audit_window: AuditWindow | None = None
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
        self.plot_chat_panel = PlotChatPanel(self.data.messages, self.workspace_splitter)
        self.workspace_splitter.addWidget(self.chapter_sidebar)
        self.workspace_splitter.addWidget(self.manuscript_panel)
        self.workspace_splitter.addWidget(self.plot_chat_panel)
        self.workspace_splitter.setStretchFactor(0, 0)
        self.workspace_splitter.setStretchFactor(1, 1)
        self.workspace_splitter.setStretchFactor(2, 0)
        self.workspace_splitter.setSizes([280, 760, 360])
        layout.addWidget(self.workspace_splitter, 1)
        self.setCentralWidget(surface)
        self.manuscript_panel.brief_requested.connect(self.open_brief_dialog)
        self.plot_chat_panel.brief_draft_requested.connect(self.open_brief_dialog)
        self.plot_chat_panel.detach_requested.connect(self.open_detached_chat)
        self.chapter_sidebar.memory_requested.connect(self.open_memory_window)
        self.chapter_sidebar.style_requested.connect(self.open_style_rules_window)
        self.chapter_sidebar.audit_requested.connect(self.open_audit_window)
        self.manuscript_panel.audit_requested.connect(self.open_audit_window)

    def open_brief_dialog(self) -> None:
        if self.brief_dialog is None:
            self.brief_dialog = BriefDialog(self.data.brief, self)
        self.brief_dialog.show()
        self.brief_dialog.raise_()
        self.brief_dialog.activateWindow()

    def open_detached_chat(self) -> None:
        if self.detached_chat_window is None:
            self.detached_chat_window = DetachedChatWindow(
                self.plot_chat_panel.message_snapshot(), self
            )
        self.detached_chat_window.show()
        self.detached_chat_window.raise_()
        self.detached_chat_window.activateWindow()

    def open_memory_window(self) -> None:
        if self.memory_window is None:
            self.memory_window = MemoryWindow(self.data, self)
        self._show_workspace_window(self.memory_window)

    def open_style_rules_window(self) -> None:
        if self.style_rules_window is None:
            self.style_rules_window = StyleRulesWindow(self.data, self)
        self._show_workspace_window(self.style_rules_window)

    def open_audit_window(self) -> None:
        if self.audit_window is None:
            self.audit_window = AuditWindow(self.data, self)
        self._show_workspace_window(self.audit_window)

    @staticmethod
    def _show_workspace_window(window: QMainWindow) -> None:
        window.show()
        window.raise_()
        window.activateWindow()

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
