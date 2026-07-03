from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QFrame,
    QLabel,
    QMainWindow,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from ai_novel_studio.application.model_runtime import ModelRuntime
from ai_novel_studio.application.model_tasks import NormalizedBrief, StyleAuditResult
from ai_novel_studio.infrastructure.llm import LLMMessage, UsageSnapshot
from ai_novel_studio.ui.demo_data import WorkspaceDemoData
from ai_novel_studio.ui.pages.audit_window import AuditWindow
from ai_novel_studio.ui.pages.brief_dialog import BriefDialog
from ai_novel_studio.ui.pages.detached_chat_window import DetachedChatWindow
from ai_novel_studio.ui.pages.memory_window import MemoryWindow
from ai_novel_studio.ui.pages.settings_dialog import SettingsDialog
from ai_novel_studio.ui.pages.style_rules_window import StyleRulesWindow
from ai_novel_studio.ui.panels.chapter_sidebar import ChapterSidebar
from ai_novel_studio.ui.panels.manuscript_panel import ManuscriptPanel
from ai_novel_studio.ui.panels.plot_chat_panel import PlotChatPanel
from ai_novel_studio.ui.panels.top_bar import TopBar
from ai_novel_studio.ui.theme import application_stylesheet


class MainWindow(QMainWindow):
    def __init__(self, model_runtime: ModelRuntime | None = None) -> None:
        super().__init__()
        self.setWindowTitle("AI Novel Studio")
        self.setMinimumSize(1100, 680)
        self.resize(1440, 900)
        self.setStyleSheet(application_stylesheet())
        self.model_runtime = model_runtime or ModelRuntime.create_default()

        self.data = WorkspaceDemoData.sample()
        self.brief_dialog: BriefDialog | None = None
        self.detached_chat_window: DetachedChatWindow | None = None
        self.memory_window: MemoryWindow | None = None
        self.style_rules_window: StyleRulesWindow | None = None
        self.audit_window: AuditWindow | None = None
        self.settings_dialog: SettingsDialog | None = None
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
        self.plot_chat_panel.message_sent.connect(self.request_plot_reply)
        self.plot_chat_panel.chapter_requirement_requested.connect(self.request_requirement)
        self.plot_chat_panel.detach_requested.connect(self.open_detached_chat)
        self.chapter_sidebar.memory_requested.connect(self.open_memory_window)
        self.chapter_sidebar.style_requested.connect(self.open_style_rules_window)
        self.chapter_sidebar.audit_requested.connect(self.open_audit_window)
        self.manuscript_panel.audit_requested.connect(self.open_audit_window)
        self.top_bar.settings_requested.connect(self.open_settings_dialog)
        coordinator = self.model_runtime.coordinator
        coordinator.chat_chunk.connect(self.plot_chat_panel.append_assistant_chunk)
        coordinator.chat_finished.connect(self.plot_chat_panel.finish_assistant_response)
        coordinator.requirement_ready.connect(self.apply_model_requirement)
        coordinator.brief_ready.connect(self.apply_normalized_brief)
        coordinator.audit_ready.connect(self.apply_model_audit)
        coordinator.task_failed.connect(self.show_model_error)
        coordinator.usage_changed.connect(self.update_usage)

    def open_brief_dialog(self) -> None:
        if self.brief_dialog is None:
            self.brief_dialog = BriefDialog(self.data.brief, self)
            self.brief_dialog.normalize_requested.connect(self.request_brief_normalization)
        self.brief_dialog.show()
        self.brief_dialog.raise_()
        self.brief_dialog.activateWindow()

    def request_plot_reply(self, _message: str) -> None:
        self.plot_chat_panel.begin_assistant_response()
        self.model_runtime.coordinator.start_chat(
            self._conversation_messages(),
            self.manuscript_panel.editor.toPlainText(),
            self.manuscript_panel.output_token_limit.value(),
        )

    def request_requirement(self) -> None:
        if self.manuscript_panel.requirement_locked():
            self.manuscript_panel.requirement_status.setText(
                "人工指令 · 已锁定，模型草稿未请求"
            )
            return
        self.plot_chat_panel.set_requirement_busy(True)
        self.model_runtime.coordinator.start_requirement(
            self._conversation_messages(),
            self.manuscript_panel.editor.toPlainText(),
            self.manuscript_panel.output_token_limit.value(),
        )

    def apply_model_requirement(self, text: str) -> None:
        self.manuscript_panel.apply_requirement_draft(text)
        self.plot_chat_panel.set_requirement_busy(False)

    def request_brief_normalization(self, source: str) -> None:
        if self.brief_dialog is not None:
            self.brief_dialog.normalize_button.setEnabled(False)
        self.model_runtime.coordinator.start_brief(
            source,
            self.manuscript_panel.output_token_limit.value(),
        )

    def apply_normalized_brief(self, value: object) -> None:
        if self.brief_dialog is not None and isinstance(value, NormalizedBrief):
            self.brief_dialog.apply_normalized_brief(value)

    def request_model_audit(self) -> None:
        if self.audit_window is not None:
            self.audit_window.run_model_audit_button.setEnabled(False)
            self.audit_window.run_model_audit_button.setText("审校中…")
        self.model_runtime.coordinator.start_audit(
            self.manuscript_panel.editor.toPlainText(),
            ("保持人物声音和叙述视角一致", "避免直接解释人物情绪"),
            self.manuscript_panel.output_token_limit.value(),
        )

    def apply_model_audit(self, value: object) -> None:
        if self.audit_window is not None and isinstance(value, StyleAuditResult):
            self.audit_window.apply_model_audit(value)

    def show_model_error(self, message: str) -> None:
        self.plot_chat_panel.show_model_error(message)
        self.plot_chat_panel.set_requirement_busy(False)
        self.manuscript_panel.pipeline_status_label.setText(f"模型调用失败：{message}")
        if self.brief_dialog is not None:
            self.brief_dialog.normalize_button.setEnabled(True)
        if self.audit_window is not None:
            self.audit_window.run_model_audit_button.setEnabled(True)
            self.audit_window.run_model_audit_button.setText("运行模型审校")

    def update_usage(self, value: object) -> None:
        if isinstance(value, UsageSnapshot):
            self.top_bar.update_usage(value)

    def _conversation_messages(self) -> tuple[LLMMessage, ...]:
        return tuple(
            LLMMessage(message.role, message.text)
            for message in self.plot_chat_panel.message_snapshot()
        )

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
            self.audit_window.model_audit_requested.connect(self.request_model_audit)
        self._show_workspace_window(self.audit_window)

    def open_settings_dialog(self) -> None:
        if self.settings_dialog is None:
            self.settings_dialog = SettingsDialog(
                self, controller=self.model_runtime.settings_controller
            )
        self.settings_dialog.show()
        self.settings_dialog.raise_()
        self.settings_dialog.activateWindow()

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
